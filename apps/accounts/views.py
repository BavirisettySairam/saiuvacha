from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

_VALID_LANGUAGES = {'en', 'te', 'hi', 'ta', 'kn'}


@login_required
def profile(request):
    if request.method == 'POST':
        lang = request.POST.get('language_preference', 'en')
        if lang in _VALID_LANGUAGES:
            request.user.language_preference = lang
            request.user.save(update_fields=['language_preference'])
            messages.success(request, 'Language preference saved.')
        return redirect('accounts:profile')
    return render(request, 'accounts/profile.html')
