/* Copied verbatim from paloaltohealthlabs.com /assets/js/site-nav.js (mhittle/paloaltohealthlabs.com @ 392a1c7). */
/* Shared site header behaviour: the Services dropdown and the small-screen Menu button.
   The header works without this script (links wrap; the dropdown opens on hover or keyboard focus). */
(function () {
  var nav = document.getElementById('site-nav'); if (!nav) return;
  var toggle = nav.querySelector('.pn-toggle');
  var dd = nav.querySelector('.pn-dd'), trigger = dd && dd.querySelector('.pn-dd-t');
  nav.classList.add('pn-js');
  if (toggle) toggle.hidden = false;

  function setDropdown(open) {
    if (!dd) return;
    dd.classList.toggle('pn-on', open);
    dd.classList.toggle('pn-off', !open);
    trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function setMenu(open) {
    nav.classList.toggle('pn-open', open);
    if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) setDropdown(false);
  }

  if (trigger) {
    trigger.addEventListener('click', function () { setDropdown(!dd.classList.contains('pn-on')); });
    // Hover and focus open it through CSS; clear a click-closed state when the pointer comes back.
    dd.addEventListener('mouseleave', function () { dd.classList.remove('pn-off'); if (!dd.classList.contains('pn-on')) trigger.setAttribute('aria-expanded', 'false'); });
    dd.addEventListener('mouseenter', function () { if (!dd.classList.contains('pn-off') && window.matchMedia('(min-width: 941px)').matches) trigger.setAttribute('aria-expanded', 'true'); });
  }
  if (toggle) toggle.addEventListener('click', function () { setMenu(!nav.classList.contains('pn-open')); });

  document.addEventListener('click', function (e) {
    if (dd && !dd.contains(e.target)) { dd.classList.remove('pn-on'); dd.classList.remove('pn-off'); trigger.setAttribute('aria-expanded', 'false'); }
    if (!nav.contains(e.target)) setMenu(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var wasOpen = dd && (dd.classList.contains('pn-on') || dd.contains(document.activeElement));
    if (wasOpen) { setDropdown(false); trigger.focus(); }
    else if (nav.classList.contains('pn-open')) { setMenu(false); toggle.focus(); }
  });
})();
