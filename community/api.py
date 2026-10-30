"""REST API (blueprint section 12).

Endpoints reuse the same forms and services as the website, so posting rules, rate limits,
shadow-banning and moderation behave identically for web and API clients.
"""

from django.contrib.auth import authenticate
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .forms import CommentForm, PostForm, ReportForm, SignUpForm, VerificationRequestForm
from .models import Category, Comment, Post, Tag, User, VerificationRequest
from .services import PostingBlocked, post_queryset


def form_errors(form):
    return {field: [str(error) for error in errors] for field, errors in form.errors.items()}


def serialize_post(post, detail=False):
    data = {
        'id': post.pk, 'title': post.title, 'type': post.type, 'category': post.category.slug,
        'author': post.user.username, 'author_verified': post.user.is_verified,
        'asset': post.asset.slug if post.asset else None, 'upvotes': post.upvotes,
        'comment_count': getattr(post, 'comment_count', None), 'is_locked': post.is_locked,
        'created_at': post.created_at, 'updated_at': post.updated_at, 'url': post.get_absolute_url(),
    }
    if detail:
        data.update({
            'body': post.body, 'tags': [pt.tag.slug for pt in post.tags.select_related('tag')],
            'position_type': post.position_type, 'entry_price': post.entry_price, 'target_price': post.target_price,
            'stop_loss': post.stop_loss, 'time_horizon': post.time_horizon, 'thesis_risk': post.thesis_risk,
            'disclosure': post.disclosure, 'ama_starts_at': post.ama_starts_at, 'ama_ends_at': post.ama_ends_at,
        })
    else:
        data['excerpt'] = post.body[:280]
    return data


def serialize_comment(comment):
    return {
        'id': comment.pk, 'post': comment.post_id, 'parent': comment.parent_comment_id, 'author': comment.user.username,
        'body': '' if comment.is_removed else comment.body, 'is_removed': comment.is_removed,
        'upvotes': comment.upvotes, 'created_at': comment.created_at,
    }


def paged(request, queryset, serializer):
    if not queryset.ordered:  # aggregated querysets drop Meta.ordering, which makes pages unstable
        queryset = queryset.order_by('-created_at')
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response([serializer(item) for item in page])


class WriteThrottleMixin:
    """Apply the 'write' rate limit to state-changing requests only; reads stay unthrottled."""

    throttle_scope = 'write'

    def get_throttles(self):
        return super().get_throttles() if self.request.method not in ('GET', 'HEAD', 'OPTIONS') else []


def issue_token(user):
    token, _created = Token.objects.get_or_create(user=user)
    return {'token': token.key, 'username': user.username}


# --- Auth ------------------------------------------------------------------------------

class SignupView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'auth'

    def post(self, request):
        password = request.data.get('password', '')
        form = SignUpForm({'username': request.data.get('username', ''), 'email': request.data.get('email', ''),
                           'password1': password, 'password2': password})
        if not form.is_valid():
            return Response({'errors': form_errors(form)}, status=status.HTTP_400_BAD_REQUEST)
        if services.signup_limited(request):
            return Response({'detail': _('Too many sign-ups from this network.')}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        return Response(issue_token(form.save()), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'auth'

    def post(self, request):
        identifier = str(request.data.get('username', ''))
        if services.login_locked(request, identifier):
            return Response({'detail': _('Too many failed attempts. Please wait and try again.')}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        user = authenticate(request, username=identifier, password=request.data.get('password', ''))
        if user is None:
            services.record_login_failure(request, identifier)
            return Response({'detail': _('Invalid credentials.')}, status=status.HTTP_400_BAD_REQUEST)
        services.clear_login_failures(request, identifier)
        return Response(issue_token(user))


# --- Posts ---------------------------------------------------------------------------------

class PostListView(WriteThrottleMixin, APIView):

    def get(self, request):
        posts = post_queryset(request.user)
        params = request.query_params
        if params.get('category'):
            posts = posts.filter(category__slug=params['category'])
        if params.get('tag'):
            posts = services.posts_for_tag(request.user, get_object_or_404(Tag, slug=params['tag']))
        if params.get('type') in dict(Post.POST_TYPES):
            posts = posts.filter(type=params['type'])
        if params.get('q', '').strip():
            posts = services.search_posts(posts, params['q'].strip())
        return paged(request, posts, serialize_post)

    def post(self, request):
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        data.setdefault('type', Post.TYPE_DISCUSSION)
        category = Category.objects.filter(slug=data.get('category')).first()
        data['category'] = category.pk if category else ''
        tags = data.get('tags', '')
        data['tags'] = ', '.join(tags) if isinstance(tags, list) else tags
        form = PostForm(data, user=request.user)
        if not form.is_valid():
            return Response({'errors': form_errors(form)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            post = services.publish_post(request.user, form.save(commit=False), form.cleaned_data['tags'])
        except PostingBlocked as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(serialize_post(post, detail=True), status=status.HTTP_201_CREATED)


class PostDetailView(APIView):
    def get(self, request, pk):
        post = get_object_or_404(post_queryset(request.user), pk=pk)
        return Response(serialize_post(post, detail=True))


class CommentListView(WriteThrottleMixin, APIView):

    def get(self, request, pk):
        post = get_object_or_404(post_queryset(request.user), pk=pk)
        comments = post.comments.select_related('user').order_by('created_at')
        if not (request.user.is_authenticated and request.user.is_staff):
            hidden = Q(user__is_shadow_banned=True)
            if request.user.is_authenticated:
                hidden &= ~Q(user=request.user)
            comments = comments.exclude(hidden)
        return paged(request, comments, serialize_comment)

    def post(self, request, pk):
        post = get_object_or_404(post_queryset(request.user), pk=pk)
        form = CommentForm({'body': request.data.get('body', '')})
        if not form.is_valid():
            return Response({'errors': form_errors(form)}, status=status.HTTP_400_BAD_REQUEST)
        parent = None
        if request.data.get('parent'):
            parent = get_object_or_404(Comment, pk=request.data['parent'], post=post, is_removed=False)
        try:
            comment = services.add_comment(request.user, post, form.cleaned_data['body'], parent)
        except PostingBlocked as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(serialize_comment(comment), status=status.HTTP_201_CREATED)


class UpvoteView(WriteThrottleMixin, APIView):

    def post(self, request, pk):
        post = get_object_or_404(post_queryset(request.user), pk=pk)
        if post.user == request.user:
            return Response({'detail': _('You cannot upvote your own post.')}, status=status.HTTP_400_BAD_REQUEST)
        voted = services.toggle_post_vote(request.user, post)
        return Response({'voted': voted, 'upvotes': post.upvotes})


# --- Users, tags, verification, reports ---------------------------------------------------------

class UserDetailView(APIView):
    def get(self, request, username):
        user = get_object_or_404(User, username=username)
        if user.is_shadow_banned and user != request.user and not (request.user.is_authenticated and request.user.is_staff):
            posts = 0
        else:
            posts = services.visible_posts(request.user, user.posts.all()).count()
        return Response({
            'username': user.username, 'bio': user.bio, 'karma_score': user.karma_score, 'is_verified': user.is_verified,
            'verified_type': user.verified_type if user.is_verified else '', 'joined': user.date_joined,
            'post_count': posts, 'follower_count': user.followers.count(),
        })


class TagPostsView(APIView):
    def get(self, request, slug):
        tag = get_object_or_404(Tag, slug=slug)
        posts = services.posts_for_tag(request.user, tag)
        response = paged(request, posts, serialize_post)
        response.data['tag'] = {'slug': tag.slug, 'name': tag.name, 'ticker': tag.ticker, 'company_name': tag.company_name}
        return response


class VerificationApplyView(WriteThrottleMixin, APIView):

    def post(self, request):
        if request.user.is_verified:
            return Response({'detail': _('You are already verified.')}, status=status.HTTP_400_BAD_REQUEST)
        if VerificationRequest.objects.filter(user=request.user, status='pending').exists():
            return Response({'detail': _('You already have an application awaiting review.')}, status=status.HTTP_409_CONFLICT)
        form = VerificationRequestForm(request.data)
        if not form.is_valid():
            return Response({'errors': form_errors(form)}, status=status.HTTP_400_BAD_REQUEST)
        application = form.save(commit=False)
        application.user = request.user
        application.credentials_text = application.supporting_information
        application.save()
        return Response({'id': application.pk, 'status': application.status}, status=status.HTTP_201_CREATED)


class ReportCreateView(WriteThrottleMixin, APIView):

    def post(self, request):
        form = ReportForm({'category': request.data.get('category', 'other'), 'reason': request.data.get('reason', '')})
        if not form.is_valid():
            return Response({'errors': form_errors(form)}, status=status.HTTP_400_BAD_REQUEST)
        post_id, comment_id = request.data.get('post'), request.data.get('comment')
        if bool(post_id) == bool(comment_id):
            return Response({'detail': _('Provide exactly one of "post" or "comment".')}, status=status.HTTP_400_BAD_REQUEST)
        comment = get_object_or_404(Comment.objects.select_related('post'), pk=comment_id, is_removed=False) if comment_id else None
        post = comment.post if comment else get_object_or_404(Post, pk=post_id, is_removed=False)
        if not services.can_view_post(request.user, post):
            return Response({'detail': _('Not found.')}, status=status.HTTP_404_NOT_FOUND)
        try:
            report = services.file_report(request.user, form.cleaned_data['category'], form.cleaned_data['reason'], post=post, comment=comment)
        except services.ReportError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'id': report.pk, 'status': report.status}, status=status.HTTP_201_CREATED)


class CategoryListView(APIView):
    def get(self, request):
        return Response([{'slug': c.slug, 'name': c.name, 'description': c.description,
                          'requires_verified': c.requires_verified, 'min_karma': c.min_karma} for c in Category.objects.all()])
