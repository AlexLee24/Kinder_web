// Daily Trigger windows are native <dialog>s opened modally (inert page, focus kept inside, Esc / back gesture closes,
// focus returns to the button that opened it). The page's scripts still open and close them the old way, by setting
// style.display: this keeps the dialog's modal state in step with that.
(function () {
    'use strict';
    // what closing a window by Esc / back gesture must also do (its own Cancel resets state)
    const ON_CLOSE = {
        targetModal: () => window.closeTargetModal && closeTargetModal(),
        logModal: () => window.closeLogModal && closeLogModal(),
        visibilityPlotModal: () => window.closeVisibilityPlot && closeVisibilityPlot(),
        scriptVisImageModal: () => window.closeScriptVisImageModal && closeScriptVisImageModal(),
        sendStep1Modal: () => window.cancelSendTriggerFlow && cancelSendTriggerFlow(),
        sendStep2Modal: () => window.cancelSendTriggerFlow && cancelSendTriggerFlow(),
        sendStep3Modal: () => window.cancelSendTriggerFlow && cancelSendTriggerFlow(),
        singleTriggerConfirmModal: () => window.cancelSingleTriggerFlow && cancelSingleTriggerFlow(),
    };
    function sync(dlg) {
        const shown = dlg.style.display && dlg.style.display !== 'none';
        if (shown && !dlg.open) {
            try { dlg.showModal(); } catch (e) { dlg.setAttribute('open', ''); }
        } else if (!shown && dlg.open) {
            dlg.close();
        }
    }
    function wire(dlg) {
        new MutationObserver(() => sync(dlg)).observe(dlg, { attributes: true, attributeFilter: ['style'] });
        dlg.addEventListener('close', () => {
            if (dlg.style.display === 'none') return;           // closed by the page's own code
            dlg.style.display = 'none';
            (ON_CLOSE[dlg.id] || (() => {}))();
        });
        sync(dlg);
    }
    function start() { document.querySelectorAll('dialog.pa-modal-overlay').forEach(wire); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
