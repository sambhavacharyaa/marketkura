import re
import time

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.urls import reverse_lazy
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Category, Comment, ContactMessage, NewsPost, Post, Report, StartupProfile, Tag, User, VerificationRequest, Watchlist
from .services import parse_tag_names

AVATAR_MAX_BYTES = 2 * 1024 * 1024
POST_IMAGE_MAX_BYTES = 5 * 1024 * 1024
DATETIME_LOCAL = '%Y-%m-%dT%H:%M'

# ASCII-only on purpose: Django's default UsernameField accepts any Unicode letter, which lets
# Cyrillic/Greek/etc. lookalikes (e.g. "аdmin" with a Cyrillic а, U+0430) register alongside a
# visually-identical Latin username — a classic impersonation vector. Restricting to the
# characters below closes that off without touching already-created accounts.
USERNAME_CHARSET_RE = re.compile(r'^[A-Za-z0-9._-]+$')
RESERVED_USERNAMES = {
    'admin', 'administrator', 'mod', 'moderator', 'support', 'staff',
    'marketkura', 'marketkuraa', 'official', 'root', 'system', 'null',
}


def validate_username(value):
    if not USERNAME_CHARSET_RE.match(value):
        raise forms.ValidationError(_('Usernames can only use English letters, numbers, and . _ -'))
    if value.lower() in RESERVED_USERNAMES:
        raise forms.ValidationError(_('This username is reserved.'))


def email_in_use(email, exclude_pk=None):
    return User.objects.filter(email__iexact=email).exclude(pk=exclude_pk).exists()


class HoneypotMixin(forms.Form):
    """Two lightweight, invisible anti-spam checks for public forms (signup, contact):

    - `website`: a text field real users never see or fill (hidden off-screen, aria-hidden,
      unreachable by keyboard) but that unsophisticated bots filling every field they find
      often do. Any value in it fails the form.
    - `form_rendered_at`: a hidden timestamp set when the form is first rendered. A submission
      that arrives faster than a human could plausibly read and fill the form is rejected too.

    Both fail with the same generic message, so neither gives a bot feedback on which check
    it tripped.
    """

    website = forms.CharField(required=False, widget=forms.HiddenInput(attrs={'autocomplete': 'off'}))
    form_rendered_at = forms.FloatField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['website'].label = ''
        self.fields['form_rendered_at'].label = ''
        if not self.is_bound:
            self.fields['form_rendered_at'].initial = time.time()

    def clean(self):
        cleaned_data = super().clean()
        spam_error = forms.ValidationError(_('Please try again.'))
        if cleaned_data.get('website'):
            raise spam_error
        rendered_at = cleaned_data.get('form_rendered_at')
        if rendered_at and (time.time() - rendered_at) < settings.FORM_MIN_SUBMIT_SECONDS:
            raise spam_error
        return cleaned_data


class SignUpForm(HoneypotMixin, UserCreationForm):
    email = forms.EmailField(required=True, label=_('Email'), widget=forms.EmailInput(attrs={'autocomplete': 'email'}))
    agree_to_terms = forms.BooleanField(required=True, label='')

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Built here, not at class-definition time: reverse() needs the URLconf loaded, which
        # isn't guaranteed yet when this module is first imported (e.g. at app startup).
        self.fields['agree_to_terms'].label = format_html(
            '{} <a href="{}" target="_blank" rel="noopener">{}</a> {} <a href="{}" target="_blank" rel="noopener">{}</a>',
            _('I agree to the'), reverse_lazy('terms'), _('Terms of Service'), _('and'), reverse_lazy('privacy'), _('Privacy Policy'),
        )
        self.fields['agree_to_terms'].error_messages['required'] = _('You must agree to the Terms of Service and Privacy Policy to create an account.')
        # UserCreationForm's defaults are Django's own generic, technical wording (the username
        # field's default help text doesn't even match validate_username's narrower charset
        # below, and the password fields' default help text is a dense validator-rule dump) —
        # replaced with one plain sentence each.
        self.fields['username'].help_text = _('Letters, numbers, and . _ - only. No spaces.')
        self.fields['password1'].help_text = _('At least 8 characters. Avoid common passwords or ones based on your username or email.')
        self.fields['password2'].help_text = _('Enter the same password again.')
        self.fields['username'].widget.attrs['autocomplete'] = 'username'

    def clean_email(self):
        email = self.cleaned_data['email']
        if email_in_use(email):
            raise forms.ValidationError(_('An account with this email already exists.'))
        return email

    def clean_username(self):
        username = self.cleaned_data['username']
        validate_username(username)
        return username


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label=_('Username or email'), max_length=254, widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username'}))


class PostForm(forms.ModelForm):
    tags = forms.CharField(required=False, max_length=300, label=_('Tags'), help_text=_('Comma-separated, up to 5. Example: ipo, banking'))

    class Meta:
        model = Post
        fields = ('category', 'type', 'title', 'body', 'image', 'asset', 'asset_tag', 'tags', 'position_type',
                  'entry_price', 'target_price', 'stop_loss', 'time_horizon', 'thesis_risk', 'disclosure',
                  'ama_starts_at', 'ama_ends_at')
        widgets = {
            'body': forms.Textarea(attrs={'rows': 8}),
            'thesis_risk': forms.Textarea(attrs={'rows': 3}),
            'disclosure': forms.Textarea(attrs={'rows': 3}),
            'ama_starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_LOCAL),
            'ama_ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_LOCAL),
        }
        help_texts = {
            'body': _('Markdown is supported. Posts are opinion and discussion, not investment advice.'),
            'image': _('Optional. A chart, screenshot or other supporting image, shown at the top of the post.'),
        }
        labels = {
            'category': _('Category'), 'type': _('Type'), 'title': _('Title'), 'body': _('Body'),
            'image': _('Image'), 'asset': _('Asset'), 'asset_tag': _('Asset tag'),
            'position_type': _('Position'), 'entry_price': _('Entry'), 'target_price': _('Target'),
            'stop_loss': _('Stop / exit plan'), 'time_horizon': _('Horizon'), 'thesis_risk': _('Risks'),
            'disclosure': _('Disclosure'), 'ama_starts_at': _('Starts'), 'ama_ends_at': _('Closes'),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['asset'].queryset = Tag.objects.filter(is_company=True).order_by('ticker', 'name')
        self.fields['asset'].required = False
        self.fields['category'].queryset = Category.objects.all()
        if not (user and user.is_verified):
            self.fields['type'].choices = [c for c in Post.POST_TYPES if c[0] != Post.TYPE_AMA]
            del self.fields['ama_starts_at'], self.fields['ama_ends_at']
        if self.instance.pk:
            self.fields['tags'].initial = ', '.join(pt.tag.name for pt in self.instance.tags.select_related('tag'))

    def clean(self):
        cleaned = super().clean()
        post_type = cleaned.get('type')
        if post_type == Post.TYPE_THESIS:
            if not (cleaned.get('body') or '').strip():
                self.add_error('body', _('A thesis body is required.'))
            if not cleaned.get('asset'):
                self.add_error('asset', _('Choose the company or ticker this thesis is about.'))
            if not cleaned.get('position_type'):
                self.add_error('position_type', _('Choose a position type.'))
            if not cleaned.get('entry_price'):
                self.add_error('entry_price', _('Enter a positive entry price.'))
            if not cleaned.get('time_horizon'):
                self.add_error('time_horizon', _('Choose a time horizon.'))
        if post_type == Post.TYPE_AMA and 'ama_ends_at' in self.fields:
            starts, ends = cleaned.get('ama_starts_at'), cleaned.get('ama_ends_at')
            if not ends:
                self.add_error('ama_ends_at', _('Set when the AMA closes.'))
            elif starts and ends <= starts:
                self.add_error('ama_ends_at', _('The AMA must end after it starts.'))
        return cleaned

    def clean_entry_price(self):
        value = self.cleaned_data.get('entry_price')
        if value is not None and value <= 0:
            raise forms.ValidationError(_('Entry price must be positive.'))
        return value

    def clean_target_price(self):
        value = self.cleaned_data.get('target_price')
        if value is not None and value <= 0:
            raise forms.ValidationError(_('Target price must be positive.'))
        return value

    def clean_tags(self):
        return parse_tag_names(self.cleaned_data.get('tags'))

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image and hasattr(image, 'size') and image.size > POST_IMAGE_MAX_BYTES:
            raise forms.ValidationError(_('Please upload an image under 5 MB.'))
        return image


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ('body',)
        widgets = {'body': forms.Textarea(attrs={'rows': 4})}
        labels = {'body': _('Your comment')}


class ContactForm(HoneypotMixin, forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ('name', 'email', 'subject', 'message')
        widgets = {'message': forms.Textarea(attrs={'rows': 6})}
        labels = {'name': _('Name'), 'email': _('Email'), 'subject': _('Subject'), 'message': _('Message')}


class ReportForm(forms.Form):
    category = forms.ChoiceField(choices=Report.CATEGORY_CHOICES, label=_('Reason'))
    reason = forms.CharField(required=False, max_length=1000, label=_('Details'), widget=forms.Textarea(attrs={'rows': 3}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('category') == 'other' and not (cleaned.get('reason') or '').strip():
            self.add_error('reason', _('Please describe the problem.'))
        return cleaned


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('email', 'bio', 'avatar')
        widgets = {'bio': forms.Textarea(attrs={'rows': 4})}

    def clean_email(self):
        email = self.cleaned_data['email']
        if email and email_in_use(email, self.instance.pk):
            raise forms.ValidationError(_('An account with this email already exists.'))
        return email

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if avatar and hasattr(avatar, 'size') and avatar.size > AVATAR_MAX_BYTES:
            raise forms.ValidationError(_('Please upload an image under 2 MB.'))
        return avatar


class WatchlistForm(forms.ModelForm):
    class Meta:
        model = Watchlist
        fields = ('name',)


class VerificationRequestForm(forms.ModelForm):
    class Meta:
        model = VerificationRequest
        fields = ('requested_type', 'full_name', 'application_reason', 'areas_of_expertise', 'experience',
                  'supporting_information', 'linkedin_url', 'website_url')
        widgets = {
            'application_reason': forms.Textarea(attrs={'rows': 4}),
            'areas_of_expertise': forms.Textarea(attrs={'rows': 3}),
            'experience': forms.Textarea(attrs={'rows': 4}),
            'supporting_information': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {'supporting_information': _('Credentials and licences')}


class VerificationReviewForm(forms.Form):
    rejection_reason = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))


class StartupForm(forms.ModelForm):
    class Meta:
        model = StartupProfile
        fields = ('name', 'tagline', 'description', 'sector', 'stage', 'location', 'website_url', 'looking_for')
        widgets = {'description': forms.Textarea(attrs={'rows': 6})}
        help_texts = {'looking_for': _('For example: advisors, co-founder, customers. Profiles are not offers of securities.')}


NEWS_IMAGE_MAX_BYTES = 5 * 1024 * 1024


class NewsForm(forms.ModelForm):
    class Meta:
        model = NewsPost
        fields = ('title', 'image', 'summary', 'body')
        widgets = {'summary': forms.Textarea(attrs={'rows': 2}), 'body': forms.Textarea(attrs={'rows': 10})}
        help_texts = {
            'image': _('Shown as the background of the news tile. A wide, high-contrast photo reads best once a title is overlaid on it.'),
            'summary': _('Optional. Shown in listings and search results; falls back to the start of the article.'),
        }

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image and hasattr(image, 'size') and image.size > NEWS_IMAGE_MAX_BYTES:
            raise forms.ValidationError(_('Please upload an image under 5 MB.'))
        return image
