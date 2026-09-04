from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Comment, Post, User


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ('category', 'type', 'title', 'body', 'asset_tag', 'thesis_entry', 'thesis_risk')
        widgets = {
            'body': forms.Textarea(attrs={'rows': 8}),
            'thesis_entry': forms.Textarea(attrs={'rows': 3}),
            'thesis_risk': forms.Textarea(attrs={'rows': 3}),
        }


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ('body',)
        widgets = {'body': forms.Textarea(attrs={'rows': 4})}


class ReportForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), max_length=1000)