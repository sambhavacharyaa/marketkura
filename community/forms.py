from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Comment, Post, User, VerificationRequest, Watchlist


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ('category', 'type', 'title', 'body', 'asset', 'asset_tag', 'position_type', 'entry_price', 'target_price', 'stop_loss', 'time_horizon', 'thesis_risk', 'disclosure')
        widgets = {
            'body': forms.Textarea(attrs={'rows': 8}),
            'thesis_risk': forms.Textarea(attrs={'rows': 3}),
            'disclosure': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('type') == 'thesis':
            if not cleaned.get('body', '').strip():
                self.add_error('body', 'A thesis body is required.')
            if not cleaned.get('position_type'):
                self.add_error('position_type', 'Choose a position type.')
            if not cleaned.get('entry_price'):
                self.add_error('entry_price', 'Enter a positive entry price.')
            if not cleaned.get('time_horizon'):
                self.add_error('time_horizon', 'Choose a time horizon.')
        return cleaned

    def clean_entry_price(self):
        value = self.cleaned_data.get('entry_price')
        if value is not None and value <= 0:
            raise forms.ValidationError('Entry price must be positive.')
        return value

    def clean_target_price(self):
        value = self.cleaned_data.get('target_price')
        if value is not None and value <= 0:
            raise forms.ValidationError('Target price must be positive.')
        return value


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ('body',)
        widgets = {'body': forms.Textarea(attrs={'rows': 4})}


class ReportForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), max_length=1000)


class WatchlistForm(forms.ModelForm):
    class Meta:
        model = Watchlist
        fields = ('name',)


class VerificationRequestForm(forms.ModelForm):
    class Meta:
        model = VerificationRequest
        fields = ('full_name', 'application_reason', 'areas_of_expertise', 'experience', 'supporting_information', 'website_url')
        widgets = {
            'application_reason': forms.Textarea(attrs={'rows': 4}),
            'areas_of_expertise': forms.Textarea(attrs={'rows': 3}),
            'experience': forms.Textarea(attrs={'rows': 4}),
            'supporting_information': forms.Textarea(attrs={'rows': 4}),
        }


class VerificationReviewForm(forms.Form):
    rejection_reason = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
