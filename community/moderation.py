"""Staff moderation: report queue, content actions, shadow-bans and pump-and-dump watch."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import services
from .models import Comment, Post, Report, StartupProfile, User, VerificationRequest
from .views import staff_required


def group_pending_reports():
    """Pending reports grouped per reported item, most-reported first."""
    reports = Report.objects.filter(status=Report.STATUS_PENDING).select_related(
        'reporter', 'post__user', 'post__category', 'comment__user', 'comment__post')
    groups = {}
    for report in reports:
        target = report.post or report.comment
        if target is None:
            continue  # the reported item was deleted; nothing left to review
        kind = 'post' if report.post_id else 'comment'
        group = groups.setdefault((kind, target.pk), {'kind': kind, 'target': target, 'reports': [], 'categories': set()})
        group['reports'].append(report)
        group['categories'].add(report.get_category_display())
    result = sorted(groups.values(), key=lambda g: (-len(g['reports']), g['reports'][0].created_at))
    for group in result:
        group['count'] = len(group['reports'])
        group['categories'] = sorted(group['categories'])
        group['post'] = group['target'] if group['kind'] == 'post' else group['target'].post
    return result


@staff_required
def moderation_dashboard(request):
    return render(request, 'moderation.html', {
        'groups': group_pending_reports(),
        'pump_watch': services.pump_watch(),
        'pending_verifications': VerificationRequest.objects.filter(status='pending').count(),
        'pending_startups': StartupProfile.objects.filter(is_approved=False).select_related('owner'),
        'recently_resolved': Report.objects.exclude(status=Report.STATUS_PENDING).select_related('reporter', 'reviewed_by', 'post', 'comment')[:10],
        'shadow_banned': User.objects.filter(is_shadow_banned=True).order_by('username'),
    })


def resolve_reports(target, status, reviewer):
    field = 'post' if isinstance(target, Post) else 'comment'
    Report.objects.filter(**{field: target}, status=Report.STATUS_PENDING).update(
        status=status, reviewed_by=reviewer, reviewed_at=timezone.now())


@staff_required
@require_POST
def moderation_action(request):
    kind, action = request.POST.get('target_type'), request.POST.get('action')
    model = {'post': Post, 'comment': Comment}.get(kind)
    if model is None:
        messages.error(request, _('Unknown moderation target.'))
        return redirect('moderation_dashboard')
    target = get_object_or_404(model, pk=request.POST.get('target_id') or 0)
    post = target if kind == 'post' else target.post
    author = target.user
    actioned, dismissed = Report.STATUS_ACTIONED, Report.STATUS_DISMISSED

    with transaction.atomic():
        if action == 'dismiss':
            resolve_reports(target, dismissed, request.user)
            messages.success(request, _('Reports dismissed.'))
        elif action == 'remove':
            target.is_removed = True
            target.save(update_fields=['is_removed'])
            resolve_reports(target, actioned, request.user)
            services.create_notification(
                author, request.user, 'moderation',
                _('A moderator removed your post for breaking the community guidelines.') if kind == 'post'
                else _('A moderator removed your comment for breaking the community guidelines.'), post)
            messages.success(request, _('Content removed.'))
        elif action == 'restore':
            target.is_removed = False
            target.save(update_fields=['is_removed'])
            messages.success(request, _('Content restored.'))
        elif action in ('lock', 'unlock'):
            post.is_locked = action == 'lock'
            post.save(update_fields=['is_locked'])
            if action == 'lock':
                resolve_reports(target, actioned, request.user)
            messages.success(request, _('Thread locked.') if action == 'lock' else _('Thread unlocked.'))
        elif action in ('shadowban', 'unshadowban'):
            if author.is_staff:
                messages.error(request, _('Staff accounts cannot be shadow-banned.'))
            else:
                author.is_shadow_banned = action == 'shadowban'
                author.save(update_fields=['is_shadow_banned'])
                if action == 'shadowban':
                    resolve_reports(target, actioned, request.user)
                messages.success(request, _('Shadow-ban applied. The member is not notified.') if action == 'shadowban' else _('Shadow-ban lifted.'))
        else:
            messages.error(request, _('Unknown moderation action.'))
    return redirect(services.safe_next_url(request, 'moderation_dashboard'))


@staff_required
@require_POST
def approve_startup(request, pk):
    startup = get_object_or_404(StartupProfile, pk=pk)
    startup.is_approved = True
    startup.save(update_fields=['is_approved'])
    services.create_notification(startup.owner, request.user, 'moderation', _('Your startup profile "%(name)s" is now listed.') % {'name': startup.name}, startup)
    messages.success(request, _('Startup profile approved.'))
    return redirect('moderation_dashboard')
