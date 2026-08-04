document.addEventListener('DOMContentLoaded', function() {
    const googleBtn = document.getElementById('google-signin-btn');
    const errorDisplay = document.getElementById('google-auth-error');

    function showGoogleError(message) {
        if (errorDisplay) {
            errorDisplay.textContent = message;
            errorDisplay.style.display = 'block';
        } else {
            alert(message);
        }
    }

    const googleBtnText = googleBtn?.querySelector('.google-signin-text');

    function setButtonState(enabled) {
        if (googleBtn) {
            googleBtn.disabled = !enabled;
            if (googleBtnText) {
                googleBtnText.textContent = enabled ? 'Continue with Google' : 'Signing in...';
            } else {
                googleBtn.textContent = enabled ? 'Continue with Google' : 'Signing in...';
            }
        }
    }

    if (!googleBtn) {
        return;
    }

    googleBtn.addEventListener('click', function(e) {
        e.preventDefault();
        if (!googleBtn || googleBtn.disabled) {
            return;
        }

        if (errorDisplay) {
            errorDisplay.style.display = 'none';
            errorDisplay.textContent = '';
        }

        setButtonState(false);

        auth.signInWithPopup(provider)
            .then((result) => result.user.getIdToken())
            .then((idToken) => fetch('/google-login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ token: idToken }),
            }))
            .then(async (response) => {
                if (response.ok) {
                    window.location.href = '/home';
                    return;
                }
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || 'Unknown error during login');
            })
            .catch((error) => {
                console.error('Google Sign-In Error:', error);
                if (error.code === 'auth/popup-closed-by-user') {
                    // User closed the Google popup; make the button available again without alarming them.
                    setButtonState(true);
                    return;
                }
                showGoogleError(`Google Sign-In failed: ${error.message || 'Check console for details.'}`);
                setButtonState(true);
            });
    });
});
