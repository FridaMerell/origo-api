from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.utils import timezone

from accounts.models import CodexToken, Notification, User
from origo.admin import site

site.register(User, UserAdmin)


@admin.register(Notification, site=site)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'domain', 'message', 'is_read', 'created_at', 'sent_by']
    list_filter = ['domain', 'is_read']
    search_fields = ['message', 'user__username', 'user__email']


class CodexTokenIssueForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.all())
    label = forms.CharField(max_length=100, initial='Codex')
    expires_at = forms.DateTimeField(required=False)


@admin.register(CodexToken, site=site)
class CodexTokenAdmin(admin.ModelAdmin):
    list_display = ['label', 'user', 'created_at', 'expires_at', 'revoked_at', 'last_used_at']
    list_filter = ['expires_at', 'revoked_at']
    search_fields = ['label', 'user__username', 'user__email']
    readonly_fields = ['user', 'token_hash', 'created_at', 'revoked_at', 'last_used_at']
    fields = ['user', 'label', 'token_hash', 'created_at', 'expires_at', 'revoked_at', 'last_used_at']
    actions = ['revoke_tokens']

    @admin.action(description='Revoke selected Codex tokens')
    def revoke_tokens(self, request, queryset):
        revoked = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f'Revoked {revoked} token(s).')

    def has_delete_permission(self, request, obj=None):
        return False

    def add_view(self, request, form_url='', extra_context=None):
        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == 'POST':
            form = CodexTokenIssueForm(request.POST)
            if form.is_valid():
                token, plaintext_token = CodexToken.issue(
                    form.cleaned_data['user'],
                    label=form.cleaned_data['label'],
                    expires_at=form.cleaned_data['expires_at'],
                )
                self.log_addition(request, token, [])
                response = TemplateResponse(
                    request,
                    'admin/accounts/codextoken/issued.html',
                    {
                        **self.admin_site.each_context(request),
                        'opts': self.opts,
                        'title': 'Codex token issued',
                        'token': token,
                        'plaintext_token': plaintext_token,
                    },
                )
                response['Cache-Control'] = 'no-store'
                return response
        else:
            form = CodexTokenIssueForm()

        context = {
            **self.admin_site.each_context(request),
            'opts': self.opts,
            'title': 'Issue Codex token',
            'form': form,
        }
        return TemplateResponse(request, 'admin/accounts/codextoken/issue_form.html', context)
