/**
 * fbsdk.js — Facebook JavaScript SDK wrapper for StockPerformer
 *
 * Handles:
 *   - Async SDK loader (non-blocking, injected into <head>)
 *   - FB.init() with the App ID read from the page's meta tag
 *   - Login popup flow (FB.login)
 *   - Login status check on page load (FB.getLoginStatus)
 *   - Token exchange with the StockPerformer backend (/auth/facebook/token)
 *   - Logout (FB.logout + server session invalidation)
 *   - UI state updates (button text, spinner, banner)
 *
 * Usage:
 *   1. Add  <meta name="fb:app_id" content="YOUR_APP_ID">  inside <head>
 *   2. Add  <script src="/static/fbsdk.js"></script>        before </body>
 *   3. Optionally call  FB_SDK.login()  from any button onclick
 *
 * The SDK is loaded asynchronously — no page-load penalty.
 */

(function (window, document) {
  'use strict';

  // ── Config ────────────────────────────────────────────────────────────────

  /** Read App ID from <meta name="fb:app_id"> so no secrets are hardcoded. */
  function _getAppId() {
    var meta = document.querySelector('meta[name="fb:app_id"]');
    return meta ? meta.getAttribute('content') : null;
  }

  var API_VERSION   = 'v21.0';          // Facebook Graph API version
  var LOGIN_SCOPE   = 'public_profile,email';
  var TOKEN_ENDPOINT = '/auth/facebook/token';  // StockPerformer backend route
  var _ready        = false;            // true once FB.init() has run
  var _initQueue    = [];               // callbacks waiting for SDK ready

  // ── Async SDK loader ──────────────────────────────────────────────────────

  /**
   * Injects the Facebook SDK script tag once, non-blocking.
   * Mirrors Facebook's official snippet but wrapped for reuse.
   */
  function _loadSDK() {
    if (document.getElementById('facebook-jssdk')) return;  // already injected

    var js  = document.createElement('script');
    var fjs = document.getElementsByTagName('script')[0];

    js.id    = 'facebook-jssdk';
    js.async = true;
    js.defer = true;
    js.src   = 'https://connect.facebook.net/en_US/sdk.js';

    js.onerror = function () {
      console.warn('[FB SDK] Failed to load sdk.js — check network / ad-blockers.');
    };

    fjs.parentNode.insertBefore(js, fjs);
  }

  // ── FB.init callback (called by the SDK after load) ───────────────────────

  window.fbAsyncInit = function () {
    var appId = _getAppId();
    if (!appId) {
      console.warn('[FB SDK] No <meta name="fb:app_id"> found. Facebook login disabled.');
      return;
    }

    FB.init({
      appId   : appId,
      cookie  : true,    // enable cookies so the server can read the session
      xfbml   : true,    // parse XFBML social plugins if present
      version : API_VERSION,
    });

    FB.AppEvents.logPageView();

    _ready = true;

    // Drain the init queue (calls made before SDK was ready)
    _initQueue.forEach(function (fn) { try { fn(); } catch (e) {} });
    _initQueue = [];

    // Auto-check login status silently on page load
    _checkLoginStatus();
  };

  // ── Login status check ────────────────────────────────────────────────────

  /**
   * Silently checks whether the user is already logged into Facebook
   * AND has previously authorised this app.
   * If so, exchange the cached token with the backend automatically.
   */
  function _checkLoginStatus() {
    FB.getLoginStatus(function (response) {
      if (response.status === 'connected') {
        // User is logged into Facebook and has authorised the app.
        // Exchange the token with our backend to create a server session.
        _exchangeToken(response.authResponse.accessToken, { silent: true });
      }
      // 'not_authorized' → logged into FB but hasn't authorised this app yet.
      // 'unknown'        → not logged into FB or unknown status.
      // In both cases we do nothing — wait for the user to click the button.
    }, true);  // true = force a fresh check (don't use cached result)
  }

  // ── Token exchange with StockPerformer backend ────────────────────────────

  /**
   * Sends the Facebook access_token to /auth/facebook/token.
   * The server verifies it with Facebook's debug_token endpoint,
   * fetches the user's profile, upserts the User row, and sets a session cookie.
   *
   * @param {string} accessToken  - Short-lived token from FB.login response
   * @param {object} [opts]
   * @param {boolean} [opts.silent] - If true, don't show banners on success
   */
  function _exchangeToken(accessToken, opts) {
    opts = opts || {};
    _setButtonState('loading');

    fetch(TOKEN_ENDPOINT, {
      method      : 'POST',
      credentials : 'same-origin',
      headers     : { 'Content-Type': 'application/json' },
      body        : JSON.stringify({ access_token: accessToken }),
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.ok) {
          if (!opts.silent) {
            _showBanner('Signed in with Facebook! Redirecting\u2026', 'ok');
          }
          // Redirect after a short delay so the user sees the success message
          setTimeout(function () {
            window.location.href = data.redirect || '/';
          }, opts.silent ? 0 : 900);
        } else {
          _setButtonState('idle');
          _showBanner(data.error || 'Facebook sign-in failed.', 'err');
        }
      })
      .catch(function (err) {
        _setButtonState('idle');
        _showBanner('Network error during Facebook sign-in.', 'err');
        console.error('[FB SDK] Token exchange error:', err);
      });
  }

  // ── Public: login ─────────────────────────────────────────────────────────

  /**
   * Trigger the Facebook login popup.
   * Call this from a button:  onclick="FB_SDK.login()"
   */
  function login() {
    if (!_ready) {
      // SDK not loaded yet — queue the call
      _initQueue.push(login);
      _showBanner('Loading Facebook SDK\u2026', 'info');
      return;
    }

    var appId = _getAppId();
    if (!appId) {
      _showBanner('Facebook login is not configured.', 'err');
      return;
    }

    _setButtonState('loading');

    FB.login(function (response) {
      if (response.status === 'connected' && response.authResponse) {
        _exchangeToken(response.authResponse.accessToken);
      } else if (response.status === 'not_authorized') {
        _setButtonState('idle');
        _showBanner('You declined the Facebook permission request.', 'err');
      } else {
        // User closed the popup or cancelled
        _setButtonState('idle');
      }
    }, {
      scope          : LOGIN_SCOPE,
      return_scopes  : true,    // include granted scopes in response
      auth_type      : 'rerequest', // re-ask if previously declined
    });
  }

  // ── Public: logout ────────────────────────────────────────────────────────

  /**
   * Log the user out of both Facebook and the StockPerformer session.
   * Safe to call even if the user is not logged in via Facebook.
   */
  function logout() {
    // Invalidate the StockPerformer server session first
    fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' })
      .finally(function () {
        // Then log out of Facebook if the SDK is ready and user is connected
        if (_ready) {
          FB.getLoginStatus(function (response) {
            if (response.status === 'connected') {
              FB.logout(function () {
                window.location.reload();
              });
            } else {
              window.location.reload();
            }
          });
        } else {
          window.location.reload();
        }
      });
  }

  // ── UI helpers ────────────────────────────────────────────────────────────

  /** Find the Facebook login button by data attribute or id. */
  function _getFbButton() {
    return (
      document.querySelector('[data-fb-login]') ||
      document.getElementById('fb-login-btn')
    );
  }

  var _originalButtonText = null;

  /**
   * Toggle the Facebook button between its idle and loading states.
   * @param {'idle'|'loading'} state
   */
  function _setButtonState(state) {
    var btn = _getFbButton();
    if (!btn) return;

    if (state === 'loading') {
      if (_originalButtonText === null) {
        _originalButtonText = btn.textContent || btn.innerText;
      }
      btn.disabled    = true;
      btn.textContent = 'Connecting\u2026';
      btn.style.opacity = '0.7';
    } else {
      btn.disabled    = false;
      btn.textContent = _originalButtonText || 'Facebook';
      btn.style.opacity = '';
      _originalButtonText = null;
    }
  }

  /**
   * Show a status banner on the page.
   * Looks for #auth-banner (login.html) or creates a temporary one.
   *
   * @param {string} message
   * @param {'ok'|'err'|'info'} type
   */
  function _showBanner(message, type) {
    var banner = document.getElementById('auth-banner');

    if (!banner) {
      // Create a floating banner if the page doesn't have one
      banner = document.createElement('div');
      banner.id = 'fb-sdk-banner';
      Object.assign(banner.style, {
        position   : 'fixed',
        top        : '72px',
        left       : '50%',
        transform  : 'translateX(-50%)',
        padding    : '10px 20px',
        borderRadius : '4px',
        fontFamily : 'inherit',
        fontSize   : '13px',
        fontWeight : '600',
        zIndex     : '9999',
        maxWidth   : '420px',
        textAlign  : 'center',
        boxShadow  : '0 4px 16px rgba(0,0,0,.4)',
      });
      document.body.appendChild(banner);
    }

    var styles = {
      ok   : { bg: 'rgba(63,185,80,0.15)',   color: '#3fb950', border: '1px solid #3fb950' },
      err  : { bg: 'rgba(248,81,73,0.15)',   color: '#f85149', border: '1px solid #f85149' },
      info : { bg: 'rgba(4,144,220,0.15)',   color: '#0490dc', border: '1px solid #0490dc' },
    };
    var s = styles[type] || styles.info;

    banner.style.background = s.bg;
    banner.style.color      = s.color;
    banner.style.border     = s.border;
    banner.textContent      = message;
    banner.style.display    = 'block';

    // Auto-dismiss success/info banners after 4 seconds
    if (type !== 'err') {
      setTimeout(function () {
        if (banner && banner.parentNode) {
          banner.style.display = 'none';
        }
      }, 4000);
    }
  }

  // ── checkLoginState / statusChangeCallback ────────────────────────────────

  /**
   * Equivalent of the official Facebook snippet's statusChangeCallback.
   * Called by checkLoginState() and by the XFBML <fb:login-button onlogin="...">
   * to handle the login-status response and exchange the token if connected.
   *
   * @param {object} response - FB.getLoginStatus response object
   */
  function statusChangeCallback(response) {
    if (response.status === 'connected' && response.authResponse) {
      _exchangeToken(response.authResponse.accessToken);
    } else if (response.status === 'not_authorized') {
      _setButtonState('idle');
      _showBanner('You declined the Facebook permission request.', 'err');
    }
    // 'unknown' → not logged in; do nothing
  }

  /**
   * Called by the XFBML <fb:login-button onlogin="checkLoginState()"> component
   * after the user completes the Facebook login dialog.
   * Also callable from any custom element that needs to re-check login state.
   *
   * Usage in HTML:
   *   <fb:login-button scope="public_profile,email" onlogin="checkLoginState();">
   *   </fb:login-button>
   */
  function checkLoginState() {
    FB.getLoginStatus(function (response) {
      statusChangeCallback(response);
    });
  }

  // ── Expose public API ─────────────────────────────────────────────────────

  window.FB_SDK = {
    login              : login,
    logout             : logout,
    checkLoginState    : checkLoginState,
    statusChangeCallback: statusChangeCallback,
    /**
     * Run a callback once the SDK is initialised.
     * @param {Function} fn
     */
    ready  : function (fn) {
      if (_ready) { fn(); } else { _initQueue.push(fn); }
    },
  };

  // Also expose checkLoginState at window level so it can be used directly
  // in the XFBML onlogin attribute:  onlogin="checkLoginState();"
  window.checkLoginState = checkLoginState;

  // ── Kick off the async SDK load ───────────────────────────────────────────

  _loadSDK();

}(window, document));
