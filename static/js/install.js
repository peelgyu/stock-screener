/* install.html 페이지 — 탭 전환 + 이벤트 위임 */
function showTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.textContent.toLowerCase().includes(name)));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    var el = document.getElementById('tab-' + name);
    if (el) el.classList.add('active');
}

document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-action]');
    if (!t) return;
    if (t.dataset.action === 'showTab' && t.dataset.tab) {
        showTab(t.dataset.tab);
    }
});
