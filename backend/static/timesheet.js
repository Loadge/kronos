// The timesheet pages' own script (served from /static so the page needs no inline script).
// Every switch reloads the page (the toolbar is a GET form). Keep the reader where they were, so
// toggling notes or signatures shows the before and after in place. On the freelance sheet the
// source checkboxes fold into one `sources` parameter.
(function () {
  var form = document.getElementById('ts-form');
  if (!form) return;
  var key = 'kronos-timesheet-scroll';

  form.addEventListener('change', function (e) {
    var t = e.target;
    if (t.classList && t.classList.contains('tb-src')) {
      var ids = [].slice.call(form.querySelectorAll('.tb-src:checked')).map(function (c) { return c.value; });
      document.getElementById('ts-sources').value = ids.join(',');
    }
    form.requestSubmit();
  });

  var print = form.querySelector('[data-print]');
  if (print) print.addEventListener('click', function () { window.print(); });

  form.addEventListener('submit', function () { sessionStorage.setItem(key, String(window.scrollY)); });
  var y = sessionStorage.getItem(key);
  if (y !== null) { sessionStorage.removeItem(key); window.scrollTo(0, Number(y)); }

  // The native date pickers can't cross each other: "from" is capped at "to" and vice versa.
  var from = document.getElementById('ts-from'), to = document.getElementById('ts-to');
  if (from && to) {
    from.addEventListener('input', function () { to.min = from.value; });
    to.addEventListener('input', function () { from.max = to.value; });
  }
})();
