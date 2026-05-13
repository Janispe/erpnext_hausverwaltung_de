frappe.ui.form.on('Bankauszug Import', {
  setup(frm) {
    frm.set_query('bank_account', () => ({
      filters: {
        is_company_account: 1
      }
    }));
    _installRowActionsRenderer(frm);
  },
  refresh(frm) {
    // Compute current phase first — banner, status formatter and primary
    // action all read from frm.__hv_phase.
    frm.__hv_phase = _computePhase(frm);

    if (!frm.doc.__islocal) {
      frm.add_custom_button('CSV parsen', () => parse_csv(frm), 'Aktionen');
      frm.add_custom_button('Bank Transaktionen erstellen', () => create_transactions(frm), 'Aktionen');
      frm.add_custom_button('Party in Bank Transactions neu zuordnen (alle)', () => relink_parties(frm), 'Aktionen');
      frm.add_custom_button('Saldo neu prüfen', () => refresh_saldo(frm), 'Aktionen');
      frm.add_custom_button('Nur Problemzeilen', () => applyRowFilter(frm, 'problems'), 'Filter');
      frm.add_custom_button('Nur ohne Party', () => applyRowFilter(frm, 'missing_party'), 'Filter');
      frm.add_custom_button('Nur ohne Bank Transaction', () => applyRowFilter(frm, 'missing_bank_transaction'), 'Filter');
      frm.add_custom_button('Nur ohne Zahlung', () => applyRowFilter(frm, 'missing_payment'), 'Filter');
      frm.add_custom_button('Nur Kunde', () => applyRowFilter(frm, 'customer'), 'Filter');
      frm.add_custom_button('Nur Lieferant', () => applyRowFilter(frm, 'supplier'), 'Filter');
      frm.add_custom_button('Nur Eigentümer', () => applyRowFilter(frm, 'eigentuemer'), 'Filter');
      frm.add_custom_button('Nur Eingang', () => applyRowFilter(frm, 'eingang'), 'Filter');
      frm.add_custom_button('Nur Ausgang', () => applyRowFilter(frm, 'ausgang'), 'Filter');
      frm.add_custom_button('Alle Zeilen', () => applyRowFilter(frm, 'all'), 'Filter');
      frm.add_custom_button('Nach Status sortieren', () => sortRowsByStatus(frm), 'Sortieren');
      frm.add_custom_button('Nach Buchungstag sortieren', () => sortRowsByBuchungstag(frm), 'Sortieren');
    }

    // Phase-driven primary action: only in phase 2 ist „Bank Transaktionen
    // erstellen" der wichtigste nächste Schritt.
    if (!frm.doc.__islocal && frm.__hv_phase === 'phase2') {
      frm.page.set_primary_action(__('Bank-Transaktionen erstellen'), () => create_transactions(frm));
    } else if (!frm.doc.__islocal) {
      // In allen anderen Phasen den Primary-Button entfernen, sonst bleibt der
      // alte Save/Submit-Button von Frappe sichtbar.
      try { frm.page.clear_primary_action(); } catch (e) { /* ignore */ }
    }

    _renderInfoBanner(frm);
    _installRowActionsRenderer(frm);
    applyRowFilter(frm, frm.__hv_row_filter || 'all');

    // Show the init dialog only for brand-new (unsaved) documents.
    if (frm.doc.__islocal && !frm.__hv_init_shown) {
      frm.__hv_init_shown = true;
      _showInitDialog(frm);
    }
  },
  csv_file(frm) {
    // auto parse when file changes (optional)
  }
});

function _computePhase(frm) {
  const rows = frm.doc.rows || [];
  if (!rows.length) return 'empty';
  const allHaveParty   = rows.every(r => r.party_type && r.party);
  const allHaveBT      = rows.every(r => r.bank_transaction || r.reference);
  const allHaveVoucher = rows.every(r => r.payment_entry || r.journal_entry);
  // Phasen-Logik hängt am bank_transaction, nicht am Party-Count: Zeilen
  // ohne Party können trotzdem als Journal Entry verbucht werden.
  if (!allHaveBT) {
    return allHaveParty ? 'phase2' : 'phase1';
  }
  if (!allHaveVoucher) return 'phase3';
  return 'done';
}

function _renderInfoBanner(frm) {
  const rows = frm.doc.rows || [];
  const total     = rows.length;
  const withParty = rows.filter(r => r.party_type && r.party).length;
  const withoutParty = total - withParty;
  const withBT    = rows.filter(r => r.bank_transaction || r.reference).length;
  const withoutBT = total - withBT;
  const withVoucher    = rows.filter(r => r.payment_entry || r.journal_entry).length;
  const withoutVoucher = total - withVoucher;
  const eingang   = rows.filter(r => r.richtung === 'Eingang').length;
  const ausgang   = rows.filter(r => r.richtung === 'Ausgang').length;
  const kunde     = rows.filter(r => r.party_type === 'Customer'    && r.party).length;
  const lieferant = rows.filter(r => r.party_type === 'Supplier'    && r.party).length;
  const eigent    = rows.filter(r => r.party_type === 'Eigentuemer' && r.party).length;
  const success   = rows.filter(r => r.row_status === 'success').length;
  const failed    = rows.filter(r => r.row_status === 'failed').length;
  const vorhanden = rows.filter(r => r.row_status === 'schon vorhanden').length;

  const phase = frm.__hv_phase || _computePhase(frm);
  const pill = (cls, label) => `<span class="indicator-pill ${cls}" style="margin-right:6px; margin-bottom:4px; display:inline-block;">${label}</span>`;

  // Phase-Header
  const phaseStyles = {
    phase1: { bg: '#fff4e5', fg: '#92400e', border: '#fdba74', icon: '①', title: __('Phase 1 von 3 — Parties zuordnen') },
    phase2: { bg: '#e6f0ff', fg: '#0c4a8b', border: '#7eb1ed', icon: '②', title: __('Phase 2 von 3 — Bank-Transaktionen erstellen') },
    phase3: { bg: '#fef3c7', fg: '#854d0e', border: '#fcd34d', icon: '③', title: __('Phase 3 von 3 — Belege zuordnen') },
    done:   { bg: '#e6f7ec', fg: '#15803d', border: '#86efac', icon: '✓', title: __('Abgeschlossen — alle Zeilen gebucht') },
    empty:  { bg: '#f6f6f7', fg: '#52525b', border: '#d4d4d8', icon: '◐', title: __('Noch keine Zeilen geladen') },
  };
  const cfg = phaseStyles[phase] || phaseStyles.empty;

  let header = '';
  if (phase === 'empty') {
    header = `<div style="background:${cfg.bg}; border:1px solid ${cfg.border}; border-radius:6px; padding:12px 16px; margin-bottom:10px;">`
      + `<div style="font-size:14px; color:${cfg.fg}; font-weight:600;">${cfg.icon} ${cfg.title}</div>`
      + `<div style="margin-top:4px; font-size:12px; color:${cfg.fg};">${__('Laden Sie eine CSV-Datei hoch und klicken Sie auf „CSV parsen".')}</div>`
      + `</div>`;
  } else if (phase === 'phase1') {
    header = `<div style="background:${cfg.bg}; border:1px solid ${cfg.border}; border-radius:6px; padding:12px 16px; margin-bottom:10px;">`
      + `<div style="font-size:14px; color:${cfg.fg}; font-weight:600;">${cfg.icon} ${cfg.title}</div>`
      + `<div style="margin-top:4px; font-size:12px; color:${cfg.fg};">`
      +   `<strong>${withParty}</strong> ${__('von')} <strong>${total}</strong> ${__('Zeilen zugeordnet')} – `
      +   `<strong>${withoutParty}</strong> ${__('offen.')}`
      + `</div>`
      + `<div style="margin-top:2px; font-size:11px; color:${cfg.fg}; opacity:0.85;">${__('Klick auf „⋯ Aktionen" in einer roten Zeile, um Mieter oder Lieferant zuzuweisen.')}</div>`
      + `</div>`;
  } else if (phase === 'phase2') {
    header = `<div style="background:${cfg.bg}; border:1px solid ${cfg.border}; border-radius:6px; padding:12px 16px; margin-bottom:10px;">`
      + `<div style="font-size:14px; color:${cfg.fg}; font-weight:600;">${cfg.icon} ${cfg.title}</div>`
      + `<div style="margin-top:4px; font-size:12px; color:${cfg.fg};">`
      +   `<strong>${withBT}</strong> ${__('von')} <strong>${total}</strong> ${__('gebucht')} – `
      +   `<strong>${withoutBT}</strong> ${__('bereit zum Buchen.')}`
      + `</div>`
      + `<div style="margin-top:2px; font-size:11px; color:${cfg.fg}; opacity:0.85;">${__('Oben rechts „Bank-Transaktionen erstellen" klicken.')}</div>`
      + `</div>`;
  } else if (phase === 'phase3') {
    header = `<div style="background:${cfg.bg}; border:1px solid ${cfg.border}; border-radius:6px; padding:12px 16px; margin-bottom:10px;">`
      + `<div style="font-size:14px; color:${cfg.fg}; font-weight:600;">${cfg.icon} ${cfg.title}</div>`
      + `<div style="margin-top:4px; font-size:12px; color:${cfg.fg};">`
      +   `<strong>${withVoucher}</strong> ${__('von')} <strong>${total}</strong> ${__('Belege zugeordnet')} – `
      +   `<strong>${withoutVoucher}</strong> ${__('offen.')}`
      + `</div>`
      + `<div style="margin-top:2px; font-size:11px; color:${cfg.fg}; opacity:0.85;">${__('Klick auf „⋯ Aktionen" in einer Zeile ohne Zahlung, um Payment Entry oder Journal Entry zuzuordnen.')}</div>`
      + `</div>`;
  } else if (phase === 'done') {
    header = `<div style="background:${cfg.bg}; border:1px solid ${cfg.border}; border-radius:6px; padding:12px 16px; margin-bottom:10px;">`
      + `<div style="font-size:14px; color:${cfg.fg}; font-weight:600;">${cfg.icon} ${cfg.title}</div>`
      + `<div style="margin-top:4px; font-size:12px; color:${cfg.fg};">${__('Alle')} <strong>${total}</strong> ${__('Zeilen erfolgreich verarbeitet.')}</div>`
      + `</div>`;
  }

  // Detail-Pills (Counts) — kompakter, je nach Phase priorisiert.
  let pills = '<div class="mt-1" style="line-height:1.9;">';
  pills += pill('gray', __('{0} Zeilen', [total]));
  if (eingang)   pills += pill('blue',   __('{0} Eingang', [eingang]));
  if (ausgang)   pills += pill('purple', __('{0} Ausgang', [ausgang]));
  if (phase === 'phase1') {
    if (withoutParty) pills += pill('red',   __('{0} ohne Party', [withoutParty]));
    if (withParty)    pills += pill('green', __('{0} zugeordnet', [withParty]));
  } else {
    if (kunde)     pills += pill('green',  __('{0} Kunde', [kunde]));
    if (lieferant) pills += pill('blue',   __('{0} Lieferant', [lieferant]));
    if (eigent)    pills += pill('purple', __('{0} Eigentümer', [eigent]));
    if (vorhanden) pills += pill('gray',   __('{0} bereits vorhanden', [vorhanden]));
    if (failed)    pills += pill('red',    __('{0} Fehler', [failed]));
    if (phase === 'phase2') {
      if (withoutBT) pills += pill('orange', __('{0} bereit zum Buchen', [withoutBT]));
      if (success)   pills += pill('green',  __('{0} ✓ erstellt', [success]));
    } else if (phase === 'phase3') {
      if (withVoucher)    pills += pill('green',  __('{0} ✓ verbucht', [withVoucher]));
      if (withoutVoucher) pills += pill('orange', __('{0} offen', [withoutVoucher]));
    } else if (phase === 'done') {
      if (success) pills += pill('green', __('{0} ✓ verbucht', [success]));
    }
  }
  pills += '</div>';

  frm.set_df_property('info', 'options', header + pills);
  if (frm.fields_dict && frm.fields_dict.info && frm.fields_dict.info.refresh) {
    frm.fields_dict.info.refresh();
  }
}

function _showInitDialog(frm) {
  const d = new frappe.ui.Dialog({
    title: __('Neuen Bankauszug importieren'),
    fields: [
      {
        fieldtype: 'Link',
        fieldname: 'bank_account',
        label: __('Bankkonto'),
        options: 'Bank Account',
        reqd: 1,
        get_query: () => ({ filters: { is_company_account: 1 } }),
      },
      {
        fieldtype: 'Attach',
        fieldname: 'csv_file',
        label: __('CSV-Datei'),
        reqd: 1,
        description: __('Postbank-CSV mit Buchungstag, IBAN und Betrag.'),
      },
    ],
    primary_action_label: __('Speichern & parsen'),
    primary_action(values) {
      d.hide();
      frm.set_value('bank_account', values.bank_account);
      frm.set_value('csv_file', values.csv_file);
      frm.save().then(() => {
        // Use the existing parse_csv helper so the user sees the same flow.
        parse_csv(frm);
      }).catch(() => {
        frappe.show_alert({ message: __('Speichern fehlgeschlagen.'), indicator: 'red' });
      });
    },
  });
  d.show();
}

function _ensureRowActionsStyles() {
  if (document.getElementById('hv-row-actions-style')) return;
  const css = `
    /* Keep the static-area (with our injected button) visible for the
       Aktionen column even when the grid row is in edit mode. */
    .grid-row .grid-static-col[data-fieldname="aktionen"] .static-area { display: inline-block !important; }
    .grid-row.editable-row .grid-static-col[data-fieldname="aktionen"] .static-area { display: inline-block !important; }
    .grid-row.editable-row .grid-static-col[data-fieldname="aktionen"] .field-area { display: none !important; }
    .grid-row .grid-static-col[data-fieldname="aktionen"] { padding-top: 4px; padding-bottom: 4px; }
    .hv-row-actions-btn { white-space: nowrap; }
    .grid-row.hv-row-click-opens-actions .grid-static-col:not(.grid-row-check):not([data-fieldname="idx"]):not([data-fieldname="aktionen"]),
    .grid-row .data-row.hv-row-click-opens-actions .grid-static-col:not(.grid-row-check):not([data-fieldname="idx"]):not([data-fieldname="aktionen"]) { cursor: pointer; }

    /* Status-Pill: auch im Edit-Mode sichtbar halten. */
    .grid-row .grid-static-col[data-fieldname="row_status"] .static-area { display: inline-block !important; }
    .grid-row.editable-row .grid-static-col[data-fieldname="row_status"] .static-area { display: inline-block !important; }
    .grid-row.editable-row .grid-static-col[data-fieldname="row_status"] .field-area { display: none !important; }

    /* Problemzeilen — dezente rote Border links, damit man sie auf einen
       Blick findet, ohne dass die Tabelle bunt wirkt. */
    .grid-row.hv-row-problem { box-shadow: inset 3px 0 0 0 #dc3545; }
  `;
  const style = document.createElement('style');
  style.id = 'hv-row-actions-style';
  style.textContent = css;
  document.head.appendChild(style);
}

function _installRowActionsRenderer(frm) {
  _ensureRowActionsStyles();
  const grid = frm.fields_dict && frm.fields_dict.rows && frm.fields_dict.rows.grid;
  if (!grid) return;

  // Bind once. We act on mousedown (not click) because Frappe enters row-edit
  // mode on mousedown, which replaces our static-area HTML — the button DOM
  // would be gone before a click handler ever fires. Stopping propagation here
  // also prevents the row from switching to edit mode.
  if (!frm.__hv_row_actions_bound) {
    const openActionsFromGridRow = function (ev, rowElement) {
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
      const $row = $(rowElement).closest('.grid-row');
      const cdn = $row.attr('data-name');
      if (!cdn) return false;
      const row = frappe.get_doc('Bankauszug Import Row', cdn);
      if (row) _openRowActions(frm, row);
      return false;
    };

    const shouldOpenActionsFromCell = function (ev, cellElement) {
      const $cell = $(cellElement);
      if ($cell.is('[data-fieldname="aktionen"], [data-fieldname="idx"], .grid-row-check')) return false;
      if ($(ev.target).closest('button, .btn, a, input, select, textarea, [role="button"], .grid-row-check').length) return false;
      return !!$cell.closest('.grid-row[data-name]').attr('data-name');
    };

    const captureRowClick = function (ev) {
      const cell = ev.target && ev.target.closest && ev.target.closest('.grid-static-col');
      if (!cell) return;
      if (!frm.fields_dict.rows.$wrapper.get(0).contains(cell)) return;
      if (!shouldOpenActionsFromCell(ev, cell)) return;
      openActionsFromGridRow(ev, cell);
    };

    const wrapperEl = frm.fields_dict.rows.$wrapper.get(0);
    if (wrapperEl) {
      wrapperEl.addEventListener('mousedown', captureRowClick, true);
      wrapperEl.addEventListener('click', captureRowClick, true);
    }
    if (!window.__hv_bankauszug_row_actions_capture_bound) {
      document.addEventListener('mousedown', function (ev) {
        const activeFrm = window.cur_frm;
        if (!activeFrm || activeFrm.doctype !== 'Bankauszug Import') return;
        const rowsField = activeFrm.fields_dict && activeFrm.fields_dict.rows;
        const wrapper = rowsField && rowsField.$wrapper && rowsField.$wrapper.get(0);
        if (!wrapper) return;
        const cell = ev.target && ev.target.closest && ev.target.closest('.grid-static-col');
        if (!cell || !wrapper.contains(cell)) return;
        const $cell = $(cell);
        if ($cell.is('[data-fieldname="aktionen"], [data-fieldname="idx"], .grid-row-check')) return;
        if ($(ev.target).closest('button, .btn, a, input, select, textarea, [role="button"], .grid-row-check').length) return;
        const rowElement = cell.closest('.grid-row[data-name]');
        const cdn = rowElement && rowElement.getAttribute('data-name');
        if (!cdn) return;
        const row = frappe.get_doc('Bankauszug Import Row', cdn);
        if (!row) return;
        ev.preventDefault();
        ev.stopPropagation();
        if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
        _openRowActions(activeFrm, row);
      }, true);
      document.addEventListener('click', function (ev) {
        const activeFrm = window.cur_frm;
        if (!activeFrm || activeFrm.doctype !== 'Bankauszug Import') return;
        const rowsField = activeFrm.fields_dict && activeFrm.fields_dict.rows;
        const wrapper = rowsField && rowsField.$wrapper && rowsField.$wrapper.get(0);
        if (!wrapper) return;
        const cell = ev.target && ev.target.closest && ev.target.closest('.grid-static-col');
        if (!cell || !wrapper.contains(cell)) return;
        const $cell = $(cell);
        if ($cell.is('[data-fieldname="aktionen"], [data-fieldname="idx"], .grid-row-check')) return;
        if ($(ev.target).closest('button, .btn, a, input, select, textarea, [role="button"], .grid-row-check').length) return;
        if (!cell.closest('.grid-row[data-name]')) return;
        ev.preventDefault();
        ev.stopPropagation();
        if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
      }, true);
      window.__hv_bankauszug_row_actions_capture_bound = true;
    }

    const handler = function (ev) {
      return openActionsFromGridRow(ev, this);
    };
    // mousedown fires the dialog and stops Frappe's edit-mode trigger.
    frm.fields_dict.rows.$wrapper.on('mousedown', '.hv-row-actions-btn', handler);
    // Also fire on any click within the actions column — covers the case where
    // the row is already in edit mode and the static-area button is hidden.
    frm.fields_dict.rows.$wrapper.on('mousedown', '.grid-static-col[data-fieldname="aktionen"]', handler);
    // Suppress the trailing click as well so nothing else reacts to it.
    frm.fields_dict.rows.$wrapper.on('click', '.hv-row-actions-btn, .grid-static-col[data-fieldname="aktionen"]', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
      return false;
    });

    frm.fields_dict.rows.$wrapper.on('mousedown', '.grid-row.hv-row-click-opens-actions .grid-static-col', function (ev) {
      if (!shouldOpenActionsFromCell(ev, this)) return;
      return openActionsFromGridRow(ev, this);
    });
    frm.fields_dict.rows.$wrapper.on('click', '.grid-row.hv-row-click-opens-actions .grid-static-col', function (ev) {
      if (!shouldOpenActionsFromCell(ev, this)) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
      return false;
    });
    frm.__hv_row_actions_bound = true;
  }

  // Also observe the grid wrapper so that when Frappe re-renders rows
  // (CSV parse, filter change, pagination, …), our injected HTML wird neu
  // gesetzt. Render-Funktionen sind idempotent, sonst würde der Observer
  // sich selbst triggern (Endlosschleife).
  if (!frm.__hv_row_actions_observer) {
    const target = frm.fields_dict.rows.$wrapper.get(0);
    if (target && typeof MutationObserver !== 'undefined') {
      const obs = new MutationObserver(() => {
        _renderAllRowActions(frm);
        _renderAllRowStatus(frm);
      });
      obs.observe(target, { childList: true, subtree: true });
      frm.__hv_row_actions_observer = obs;
    }
  }

  _renderAllRowActions(frm);
  _renderAllRowStatus(frm);
}

function _renderAllRowActions(frm) {
  const grid = frm.fields_dict && frm.fields_dict.rows && frm.fields_dict.rows.grid;
  if (!grid || !Array.isArray(grid.grid_rows)) return;
  grid.grid_rows.forEach((gridRow) => {
    if (!gridRow || !gridRow.row) return;
    gridRow.row.addClass('hv-row-click-opens-actions');
    gridRow.row.closest('.grid-row[data-name]').addClass('hv-row-click-opens-actions');
    const $cell = gridRow.row.find('[data-fieldname="aktionen"] .static-area');
    const $target = $cell.length ? $cell : gridRow.row.find('[data-fieldname="aktionen"]');
    if (!$target.length) return;
    if ($target.find('.hv-row-actions-btn').length) return;
    $target.empty().append(
      $('<button>')
        .attr('type', 'button')
        .attr('tabindex', '-1')
        .addClass('btn btn-xs btn-default hv-row-actions-btn')
        .html('⋯ ' + __('Aktionen'))
    );
  });
}

function _computeRowStatusPill(row, phase) {
  const colorMap = { green: '#28a745', red: '#dc3545', gray: '#8d99a6', orange: '#f59f00', blue: '#1f75cb' };
  const v = (row.row_status || '').toString().trim();
  const hasBT      = !!(row.bank_transaction || row.reference);
  const hasVoucher = !!(row.payment_entry || row.journal_entry);

  // In Phase 3 / done unterscheiden wir „BT erstellt, aber kein Beleg" vs.
  // „komplett verbucht" — sonst zeigen wir alle row_status='success' Zeilen
  // als grün/„Erstellt", obwohl der Reconciliation-Schritt noch fehlt.
  if ((phase === 'phase3' || phase === 'done') && hasBT) {
    if (hasVoucher) return { color: colorMap.green,  label: __('✓ Verbucht') };
    return            { color: colorMap.orange, label: __('○ Beleg fehlt') };
  }

  const map = {
    'success':         { color: colorMap.green, label: __('✓ Erstellt') },
    'failed':          { color: colorMap.red,   label: __('✗ Fehler') },
    'schon vorhanden': { color: colorMap.gray,  label: __('• Vorhanden') },
  };
  if (v && map[v])    return map[v];
  if (v)              return { color: colorMap.gray, label: v };
  if (phase === 'phase1') {
    return (row.party_type && row.party)
      ? { color: colorMap.green, label: __('✓ Zugeordnet') }
      : { color: colorMap.red,   label: __('✗ Nicht zugeordnet') };
  }
  // phase2
  return (row.party_type && row.party)
    ? { color: colorMap.blue,   label: __('• Bereit') }
    : { color: colorMap.orange, label: __('• Ohne Party') };
}

function _renderAllRowStatus(frm) {
  const grid = frm.fields_dict && frm.fields_dict.rows && frm.fields_dict.rows.grid;
  if (!grid || !Array.isArray(grid.grid_rows)) return;
  const phase = frm.__hv_phase || _computePhase(frm);

  grid.grid_rows.forEach((gridRow) => {
    if (!gridRow || !gridRow.row) return;
    const r = gridRow.doc || (locals['Bankauszug Import Row'] || {})[gridRow.docname];
    if (!r) return;

    const pill = _computeRowStatusPill(r, phase);
    const key = `${pill.color}|${pill.label}`;

    const $cell = gridRow.row.find('[data-fieldname="row_status"] .static-area');
    const $target = $cell.length ? $cell : gridRow.row.find('[data-fieldname="row_status"]');
    if ($target.length) {
      const $existing = $target.find('.hv-row-status-pill');
      // Idempotent: nur neu rendern wenn sich der Inhalt ändert,
      // sonst triggert der MutationObserver sich selbst.
      if (!$existing.length || $existing.attr('data-hv-key') !== key) {
        const safe = frappe.utils.escape_html(pill.label);
        $target.html(
          `<span class="hv-row-status-pill" data-hv-key="${key}" `
          + `style="display:inline-flex; align-items:center; gap:6px; font-size:11px; color:${pill.color}; font-weight:500; white-space:nowrap;">`
          + `<span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${pill.color};"></span>`
          + safe
          + `</span>`
        );
      }
    }

    // Problem-Markierung als Border links — nur ändern wenn nötig, sonst
    // Observer-Loop.
    const isProblem = rowIsProblem(r, phase);
    if (gridRow.row.hasClass('hv-row-problem') !== isProblem) {
      gridRow.row.toggleClass('hv-row-problem', isProblem);
    }
  });
}

function refresh_saldo(frm) {
  frappe.call({
    method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.refresh_saldo',
    args: { docname: frm.doc.name },
    freeze: true,
    freeze_message: __('Saldo wird neu berechnet…'),
  }).then((r) => {
    const m = (r && r.message) || {};
    const fmt = (v) => frappe.format(parseFloat(v || 0), { fieldtype: 'Currency' });
    const diff = parseFloat(m.saldo_differenz || 0);
    const indicator = Math.abs(diff) < 0.01 ? 'green' : 'red';
    const status = Math.abs(diff) < 0.01 ? __('passt') : __('Differenz {0}', [fmt(diff)]);
    frappe.msgprint({
      title: __('Saldo-Vergleich'),
      message: __('Stichtag: {0}<br>Saldo laut Bank: <b>{1}</b><br>Saldo laut ERP: <b>{2}</b><br>Differenz: <b>{3}</b> ({4})', [
        m.saldo_datum || '-',
        fmt(m.saldo_laut_csv),
        fmt(m.saldo_laut_erp),
        fmt(diff),
        status,
      ]),
      indicator,
    });
    frm.reload_doc();
  });
}

function parse_csv(frm) {
  if (!frm.doc.csv_file) {
    frappe.msgprint('Bitte zuerst eine CSV-Datei hochladen.');
    return;
  }
  frappe.call({
    method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.parse_csv',
    args: { docname: frm.doc.name },
    freeze: true,
    freeze_message: 'CSV wird verarbeitet…',
    callback: (r) => {
      frm.reload_doc();
      if (r && r.message) {
        frappe.show_alert(`Geladen: ${r.message.count} Zeilen`);
      }
    }
  });
}

function _buildCreateSummary(msg) {
  const created = msg.created || [];
  const errors = msg.errors || [];
  const auto_matched = msg.auto_matched || [];
  const auto_match_failed = msg.auto_match_failed || [];
  const created_without_party = msg.created_without_party || 0;
  const skipped_before_cutoff = msg.skipped_before_cutoff || 0;
  const cutoff_date = msg.cutoff_date || null;
  let summary = __('Erstellt: {0}', [created.length]);
  if (auto_matched.length) summary += ', ' + __('Auto-zugeordnet: {0}', [auto_matched.length]);
  const not_matched = created.length - auto_matched.length;
  if (created.length && not_matched > 0) summary += ', ' + __('manuell zuzuordnen: {0}', [not_matched]);
  if (skipped_before_cutoff) summary += ', ' + __('vor Start-Datum übersprungen: {0}', [skipped_before_cutoff]);
  if (errors.length) summary += ', ' + __('Fehler: {0}', [errors.length]);
  if (created_without_party) summary += ', ' + __('ohne Party: {0}', [created_without_party]);
  if (cutoff_date && skipped_before_cutoff) {
    summary += '<br><span style="font-size:11px; color:#888;">' + __('Start-Datum: {0} (Hausverwaltung Einstellungen)', [cutoff_date]) + '</span>';
  }
  return summary;
}

function create_transactions(frm) {
  if (!frm.doc.bank_account) {
    frappe.msgprint('Bitte wählen Sie ein Bankkonto.');
    return;
  }

  const runCreate = (allowMissingParty) => {
    return frappe.call({
      method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.create_bank_transactions',
      args: { docname: frm.doc.name, allow_missing_party: allowMissingParty ? 1 : 0 },
      freeze: true,
      freeze_message: 'Transaktionen werden erstellt…',
    });
  };

  runCreate(false).then((r) => {
    const msg = (r && r.message) || {};
    const warning = msg.warning || null;
    const needsConfirm = warning && warning.requires_confirmation;

    if (needsConfirm) {
      const preview = (warning.preview_lines || []).slice(0, 8).join('<br>');
      const confirmHtml = [
        __('{0} Zeilen ohne Party gefunden.', [warning.missing_count || 0]),
        preview ? `<br><br>${preview}` : '',
        '<br><br>',
        __('Trotzdem Bank Transaktionen erstellen?')
      ].join('');

      frappe.confirm(confirmHtml, () => {
        runCreate(true).then((res2) => {
          frm.reload_doc();
          frappe.msgprint(_buildCreateSummary((res2 && res2.message) || {}));
        }).catch((err) => {
          let details = '';
          try {
            const serverMessages = err && err._server_messages ? JSON.parse(err._server_messages) : [];
            details = serverMessages && serverMessages.length ? serverMessages.join('<br>') : '';
          } catch (e) {
            details = '';
          }
          frappe.msgprint(details || __('Bank Transaktionen konnten nicht erstellt werden.'));
        });
      });
      return;
    }

    frm.reload_doc();
    frappe.msgprint(_buildCreateSummary(msg));
  }).catch((err) => {
    let details = '';
    try {
      const serverMessages = err && err._server_messages ? JSON.parse(err._server_messages) : [];
      details = serverMessages && serverMessages.length ? serverMessages.join('<br>') : '';
    } catch (e) {
      details = '';
    }
    frappe.msgprint(details || __('Bank Transaktionen konnten nicht erstellt werden.'));
  });
}

function rowMatchesFilter(row, mode, phase) {
  if (mode === 'missing_party') {
    return !(row.party_type && row.party);
  }
  if (mode === 'missing_bank_transaction') {
    return !(row.bank_transaction || row.reference);
  }
  if (mode === 'missing_payment') {
    // Zeile hat eine Bank Transaction, aber noch keine Zahlung/Buchung verknüpft
    const hasBT = !!(row.bank_transaction || row.reference);
    const hasVoucher = !!(row.payment_entry || row.journal_entry);
    return hasBT && !hasVoucher;
  }
  if (mode === 'problems') {
    // Phase 1: Probleme = fehlende Partei (das ist hier der Hauptfokus).
    // Phase 2/done: Probleme = failed-Status, Error, oder noch ohne Bank-Transaktion,
    // ODER BT da aber noch keine Zahlung/Buchung zugeordnet (offene Reconciliation).
    if (phase === 'phase1') {
      return !(row.party_type && row.party);
    }
    if (row.row_status === 'failed') return true;
    if ((row.error || '').toString().trim()) return true;
    if (!(row.bank_transaction || row.reference)) return true;
    if ((row.bank_transaction || row.reference) && !(row.payment_entry || row.journal_entry)) return true;
    return false;
  }
  if (mode === 'customer')   return row.party_type === 'Customer';
  if (mode === 'supplier')   return row.party_type === 'Supplier';
  if (mode === 'eigentuemer') return row.party_type === 'Eigentuemer';
  if (mode === 'eingang')    return row.richtung === 'Eingang';
  if (mode === 'ausgang')    return row.richtung === 'Ausgang';
  return true;
}

function rowIsProblem(row, phase) {
  return rowMatchesFilter(row || {}, 'problems', phase);
}

function ensureGridDataFilterPatch(frm, grid) {
  if (!grid || grid.__hv_get_data_patched) return;

  const originalGetData = grid.get_data.bind(grid);
  grid.get_data = function (filter_field) {
    const data = originalGetData(filter_field) || [];
    const mode = frm.__hv_row_filter || 'all';
    if (mode === 'all') return data;
    return data.filter((row) => rowMatchesFilter(row || {}, mode, frm.__hv_phase));
  };

  grid.__hv_get_data_patched = true;
}

function applyRowFilter(frm, mode) {
  frm.__hv_row_filter = mode || 'all';
  const grid = frm.fields_dict && frm.fields_dict.rows && frm.fields_dict.rows.grid;
  if (!grid) return;

  ensureGridDataFilterPatch(frm, grid);

  if (grid.grid_pagination && typeof grid.grid_pagination.go_to_page === 'function') {
    grid.grid_pagination.go_to_page(1);
  }
  grid.refresh();

  const allRows = frm.doc.rows || [];
  const visible = allRows.filter((row) => rowMatchesFilter(row || {}, frm.__hv_row_filter, frm.__hv_phase)).length;

  const filterLabels = {
    missing_party:               { label: __('Zeilen ohne Party'),                indicator: 'orange' },
    missing_bank_transaction:    { label: __('Zeilen ohne Bank Transaction'),     indicator: 'orange' },
    missing_payment:             { label: __('Zeilen ohne Zahlung'),              indicator: 'orange' },
    problems:                    { label: __('Problemzeilen'),                    indicator: visible ? 'orange' : 'green' },
    customer:                    { label: __('Kunde-Zeilen'),                     indicator: 'green' },
    supplier:                    { label: __('Lieferant-Zeilen'),                 indicator: 'blue' },
    eigentuemer:                 { label: __('Eigentümer-Zeilen'),                indicator: 'purple' },
    eingang:                     { label: __('Eingang-Zeilen'),                   indicator: 'blue' },
    ausgang:                     { label: __('Ausgang-Zeilen'),                   indicator: 'purple' },
  };
  const cfg = filterLabels[frm.__hv_row_filter];
  if (cfg) {
    frappe.show_alert({
      message: __('Filter aktiv: {0} {1}', [visible, cfg.label]),
      indicator: cfg.indicator,
    });
  }
}

function relink_parties(frm) {
  frappe.confirm(
    __('Bestehende Party-Zuordnungen in Bank Transactions werden überschrieben, wenn neue Treffer gefunden werden. Fortfahren?'),
    () => {
      frappe.call({
        method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.relink_parties_for_all_rows',
        args: { docname: frm.doc.name, overwrite: 1 },
        freeze: true,
        freeze_message: __('Bank Transactions werden neu zugeordnet...'),
      }).then((r) => {
        const msg = (r && r.message) || {};
        const updated = msg.updated || 0;
        const rowUpdated = msg.row_updated || 0;
        const unchanged = msg.unchanged || 0;
        const skipped = msg.skipped || 0;
        const errors = (msg.errors || []).length;
        const changes = msg.changes || [];
        const skippedRows = msg.skipped_rows || [];

        let summary = __('BT aktualisiert: {0}, Zeilen aktualisiert: {1}, Unverändert: {2}, Übersprungen: {3}, Fehler: {4}', [
          updated, rowUpdated, unchanged, skipped, errors
        ]);

        if (skippedRows.length) {
          const byReason = skippedRows.reduce((acc, r) => {
            const reason = r.reason || 'unknown';
            acc[reason] = (acc[reason] || 0) + 1;
            return acc;
          }, {});
          const reasonText = Object.entries(byReason).map(([k, v]) => `${k}: ${v}`).join(', ');
          summary += `<br><br><b>${__('Übersprungen (Gründe)')}</b><br>${reasonText}`;
        }

        if (changes.length) {
          const preview = changes.slice(0, 8).map((c) =>
            `${c.bank_transaction}: ${c.from_party_type || '-'} ${c.from_party || '-'} -> ${c.to_party_type} ${c.to_party}`
          );
          summary += `<br><br><b>${__('Änderungen')}</b><br>${preview.join('<br>')}`;
          if (changes.length > 8) {
            summary += `<br>${__('... und {0} weitere', [changes.length - 8])}`;
          }
        }
        if (errors > 0) {
          const previewErrors = (msg.errors || []).slice(0, 3).map((e) => `${e.row}: ${(e.error || '').split('\n')[0]}`);
          summary += `<br><br><b>${__('Fehler (Auszug)')}</b><br>${previewErrors.join('<br>')}`;
        }
        frappe.msgprint(summary);
        frm.reload_doc();
      }).catch((err) => {
        const fallback = __('Neuzuordnung fehlgeschlagen. Bitte Browser-Konsole und Server-Logs prüfen.');
        let details = '';
        try {
          const serverMessages = err && err._server_messages ? JSON.parse(err._server_messages) : [];
          details = serverMessages && serverMessages.length ? serverMessages.join('<br>') : '';
        } catch (e) {
          details = '';
        }
        frappe.msgprint(details ? `${fallback}<br><br>${details}` : fallback);
      });
    }
  );
}

function defaultPartyName(row) {
  return (row.auftraggeber || row.verwendungszweck || '').trim();
}

function defaultPartyType(row) {
  if (row.party_type) return row.party_type;
  return row.richtung === 'Ausgang' ? 'Supplier' : 'Customer';
}

const HV_AUTOLINK_KEY = 'hv_bankauszug_autolink_context';

function setAutoLinkContext(ctx) {
  try {
    localStorage.setItem(HV_AUTOLINK_KEY, JSON.stringify({
      ...ctx,
      ts: Date.now(),
      done: 0,
    }));
  } catch (e) {
    // ignore storage issues
  }
}

function _prepareCustomer(frm, row) {
  setAutoLinkContext({
    import_docname: frm.doc.name,
    row_name: row.name,
    expected_doctype: 'Customer',
    party_type: 'Customer',
    iban: row.iban || '',
  });
  frappe.new_doc('Customer', {
    customer_name: defaultPartyName(row),
    customer_type: 'Individual',
  });
}

function _prepareSupplier(frm, row) {
  setAutoLinkContext({
    import_docname: frm.doc.name,
    row_name: row.name,
    expected_doctype: 'Supplier',
    party_type: 'Supplier',
    iban: row.iban || '',
  });
  frappe.new_doc('Supplier', {
    supplier_name: defaultPartyName(row),
    supplier_type: 'Company',
  });
}

function _prepareBankAccount(frm, row) {
  const d = new frappe.ui.Dialog({
    title: __('Bankkonto erstellen'),
    fields: [
      {
        fieldtype: 'Select',
        fieldname: 'party_type',
        label: __('Party Typ'),
        options: 'Customer\nSupplier\nEigentuemer',
        default: defaultPartyType(row),
        reqd: 1,
      },
      {
        fieldtype: 'Dynamic Link',
        fieldname: 'party',
        label: __('Party'),
        options: 'party_type',
      },
      {
        fieldtype: 'Data',
        fieldname: 'iban',
        label: __('IBAN'),
        default: row.iban || '',
      },
    ],
    primary_action_label: __('Form öffnen'),
    primary_action: (values) => {
      d.hide();
      setAutoLinkContext({
        import_docname: frm.doc.name,
        row_name: row.name,
        expected_doctype: 'Bank Account',
        party_type: values.party_type || '',
      });
      frappe.new_doc('Bank Account', {
        account_name: values.party ? `Konto ${values.party}` : '',
        party_type: values.party_type || '',
        party: values.party || '',
        iban: values.iban || '',
        is_company_account: 0,
      });
    },
  });
  d.show();
}

function _openRowActions(frm, row) {
  const fmtCurrency = (v) => frappe.format(v, { fieldtype: 'Currency' });
  const fmtDate = (v) => (v ? frappe.datetime.str_to_user(v) : '-');
  const escape = (v) => frappe.utils.escape_html(v || '-');
  const partyText = row.party
    ? `${escape(row.party_type)}: ${escape(row.party)}`
    : __('nicht zugeordnet');

  const isAusgang = row.richtung === 'Ausgang';
  const customerClass = !isAusgang ? 'btn-primary' : 'btn-default';
  const supplierClass =  isAusgang ? 'btn-primary' : 'btn-default';

  const hasBT = !!row.bank_transaction;
  const alreadyReconciled = !!row.payment_entry || !!row.journal_entry;
  const showReconcileSection = hasBT && !alreadyReconciled;
  const showAbschlagAction = showReconcileSection && row.richtung === 'Ausgang' && row.party_type === 'Supplier' && row.party;
  // Kreditrate funktioniert auch ohne erkannte Party — Match läuft über Bankkonto+Betrag+Datum
  const showKreditAction = showReconcileSection && row.richtung === 'Ausgang';

  const reconcileSectionHtml = showReconcileSection
    ? `
      <div style="font-size:11px; color:#888; text-transform:uppercase; letter-spacing:0.04em; margin:14px 0 6px 0;">${__('Bank Transaction zuordnen')}</div>
      <div class="hv-row-action-buttons" style="display:flex; gap:8px; flex-wrap:wrap;">
        <button type="button" class="btn btn-primary" data-hv-action="match_invoices" style="flex:1 1 0; min-width:160px;">${__('Rechnungen zuordnen')}</button>
        ${showAbschlagAction ? `<button type="button" class="btn btn-primary" data-hv-action="match_abschlag" style="flex:1 1 0; min-width:160px;">${__('Abschlag zuordnen')}</button>` : ''}
        ${showKreditAction ? `<button type="button" class="btn btn-default" data-hv-action="match_kredit" style="flex:1 1 0; min-width:160px;">${__('Kreditrate zuordnen')}</button>` : ''}
        <button type="button" class="btn btn-default" data-hv-action="standalone_payment" style="flex:1 1 0; min-width:160px;">${__('Zahlung erstellen')}</button>
        <button type="button" class="btn btn-default" data-hv-action="journal_entry" style="flex:1 1 0; min-width:160px;">${__('Buchungssatz erstellen')}</button>
      </div>
    `
    : '';

  const reconciledNoticeHtml = alreadyReconciled
    ? `<div style="margin-top:14px; padding:8px 10px; background:#e6f7ec; border-radius:4px; font-size:12px; color:#15803d;">${__('Bereits zugeordnet')}: ${escape(row.payment_entry || row.journal_entry)}</div>`
    : '';

  const ctxHtml = `
    <div class="hv-row-context" style="margin-bottom:14px; padding:10px 12px; background:#f6f6f7; border-radius:4px; font-size:12px; line-height:1.6;">
      <div><strong>${__('Buchungstag')}:</strong> ${fmtDate(row.buchungstag)} &nbsp; • &nbsp; <strong>${__('Richtung')}:</strong> ${escape(row.richtung)} &nbsp; • &nbsp; <strong>${__('Betrag')}:</strong> ${fmtCurrency(row.betrag)}</div>
      <div><strong>${__('IBAN')}:</strong> ${escape(row.iban)}</div>
      <div><strong>${__('Auftraggeber')}:</strong> ${escape(row.auftraggeber)}</div>
      <div><strong>${__('Verwendungszweck')}:</strong> ${escape(row.verwendungszweck)}</div>
      <div><strong>${__('Aktuelle Zuordnung')}:</strong> ${partyText}</div>
    </div>
    <div style="font-size:11px; color:#888; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:6px;">${__('Bestehender Partei zuweisen')}</div>
    <div class="hv-row-action-buttons" style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px;">
      <button type="button" class="btn ${customerClass}" data-hv-action="assign_customer" style="flex:1 1 0; min-width:160px;">${__('Mieter zuweisen')}</button>
      <button type="button" class="btn ${supplierClass}" data-hv-action="assign_supplier" style="flex:1 1 0; min-width:160px;">${__('Lieferant zuweisen')}</button>
    </div>
    <div style="font-size:11px; color:#888; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:6px;">${__('Neu anlegen')}</div>
    <div class="hv-row-action-buttons" style="display:flex; gap:8px; flex-wrap:wrap;">
      <button type="button" class="btn btn-default" data-hv-action="customer" style="flex:1 1 0; min-width:160px;">${__('Mieter erstellen')}</button>
      <button type="button" class="btn btn-default" data-hv-action="supplier" style="flex:1 1 0; min-width:160px;">${__('Lieferant erstellen')}</button>
      <button type="button" class="btn btn-default" data-hv-action="bank_account" style="flex:1 1 0; min-width:160px;">${__('Bankkonto erstellen')}</button>
    </div>
    ${reconcileSectionHtml}
    ${reconciledNoticeHtml}
  `;

  const d = new frappe.ui.Dialog({
    title: __('Aktionen für Zeile {0}', [row.idx]),
    fields: [
      { fieldtype: 'HTML', fieldname: 'context', options: ctxHtml },
    ],
  });

  d.show();

  d.$wrapper.find('[data-hv-action="assign_customer"]').on('click', () => { d.hide(); _assignExistingParty(frm, row, 'Customer'); });
  d.$wrapper.find('[data-hv-action="assign_supplier"]').on('click', () => { d.hide(); _assignExistingParty(frm, row, 'Supplier'); });
  d.$wrapper.find('[data-hv-action="customer"]').on('click', () => { d.hide(); _prepareCustomer(frm, row); });
  d.$wrapper.find('[data-hv-action="supplier"]').on('click', () => { d.hide(); _prepareSupplier(frm, row); });
  d.$wrapper.find('[data-hv-action="bank_account"]').on('click', () => { d.hide(); _prepareBankAccount(frm, row); });
  d.$wrapper.find('[data-hv-action="match_invoices"]').on('click', () => { d.hide(); _openMatchInvoicesDialog(frm, row); });
  d.$wrapper.find('[data-hv-action="match_abschlag"]').on('click', () => { d.hide(); _openAbschlagDialog(frm, row); });
  d.$wrapper.find('[data-hv-action="match_kredit"]').on('click', () => { d.hide(); _openKreditrateDialog(frm, row); });
  d.$wrapper.find('[data-hv-action="standalone_payment"]').on('click', () => { d.hide(); _openStandalonePaymentDialog(frm, row); });
  d.$wrapper.find('[data-hv-action="journal_entry"]').on('click', () => { d.hide(); _openJournalEntryDialog(frm, row); });
}

function _openKreditrateDialog(frm, row) {
  frappe.call({
    method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.get_open_kreditraten_for_row',
    args: { docname: frm.doc.name, row_name: row.name },
    freeze: true,
    freeze_message: __('Suche offene Kreditraten…'),
  }).then((r) => {
    const data = (r && r.message) || {};
    const candidates = data.candidates || [];

    const fmt = (v) => frappe.format(v, { fieldtype: 'Currency' });
    const fmtDate = (v) => (v ? frappe.datetime.str_to_user(v) : '-');
    const escape = (v) => frappe.utils.escape_html(v || '');

    if (!candidates.length) {
      frappe.msgprint({
        title: __('Keine passende Kreditrate'),
        message: __(
          'Keine offene Rate gefunden für Bankkonto {0}, Betrag {1} (Toleranz pro Kreditvertrag). Bitte Kreditvertrag/Rate manuell anlegen oder Tilgungsplan ergänzen.',
          [escape(data.bank_account), fmt(data.amount)]
        ),
      });
      return;
    }

    const rowsHtml = candidates.map((c) => {
      const safeKv = escape(c.kreditvertrag);
      const safeRow = escape(c.row_name);
      return `
        <tr>
          <td style="padding:4px 8px;">
            <input type="radio" name="hv-kredit-pick" class="hv-kredit-cb"
              data-kreditvertrag="${safeKv}" data-rate-name="${safeRow}">
          </td>
          <td style="padding:4px 8px;">
            <a href="/app/kreditvertrag/${encodeURIComponent(c.kreditvertrag)}" target="_blank">${safeKv}</a>
            <span style="color:#888;"> · Zeile ${c.row_idx}</span>
          </td>
          <td style="padding:4px 8px; white-space:nowrap;">${fmtDate(c.faelligkeitsdatum)}</td>
          <td style="padding:4px 8px; text-align:right;">${fmt(c.gesamtbetrag)}</td>
          <td style="padding:4px 8px; text-align:right; color:#888;">${c.delta_days} ${__('Tage')}</td>
        </tr>
      `;
    }).join('');

    const html = `
      <div style="margin-bottom:10px; padding:8px 10px; background:#f6f6f7; border-radius:4px; font-size:12px;">
        <strong>${__('Bank-Betrag')}:</strong> ${fmt(data.amount)} &nbsp;•&nbsp;
        <strong>${__('Buchungstag')}:</strong> ${fmtDate(data.posting_date)} &nbsp;•&nbsp;
        <strong>${__('Bankkonto')}:</strong> ${escape(data.bank_account)}
        ${data.supplier ? `&nbsp;•&nbsp; <strong>${__('Lieferant')}:</strong> ${escape(data.supplier)}` : ''}
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:12px;">
        <thead>
          <tr style="background:#f6f6f7;">
            <th style="padding:4px 8px; width:30px;"></th>
            <th style="padding:4px 8px; text-align:left;">${__('Kreditvertrag')}</th>
            <th style="padding:4px 8px; text-align:left;">${__('Fälligkeit')}</th>
            <th style="padding:4px 8px; text-align:right;">${__('Betrag')}</th>
            <th style="padding:4px 8px; text-align:right;">${__('Δ Tage')}</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
      <div style="margin-top:6px; font-size:11px; color:#888;">
        ${__('Beim Übernehmen wird ein Journal Entry mit Zins-/Tilgungs-Split erzeugt und die Bank Transaction direkt verknüpft.')}
      </div>
    `;

    const d = new frappe.ui.Dialog({
      title: __('Kreditrate zuordnen — Zeile {0}', [row.idx]),
      size: 'large',
      fields: [{ fieldtype: 'HTML', fieldname: 'body', options: html }],
      primary_action_label: __('Buchen'),
      primary_action() {
        const picked = d.$wrapper.find('.hv-kredit-cb:checked');
        if (!picked.length) {
          frappe.msgprint(__('Bitte eine Rate auswählen.'));
          return;
        }
        const kreditvertrag = picked.attr('data-kreditvertrag');
        const rate_name = picked.attr('data-rate-name');
        d.disable_primary_action();
        frappe.call({
          method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.assign_kreditrate_to_bank_row',
          args: {
            docname: frm.doc.name,
            row_name: row.name,
            kreditvertrag,
            rate_name,
          },
          freeze: true,
          freeze_message: __('Buchung wird erstellt…'),
        }).then((res) => {
          const msg = (res && res.message) || {};
          frappe.show_alert({
            message: __('Kreditrate gebucht: {0} → {1}', [
              msg.kreditvertrag,
              msg.journal_entry,
            ]),
            indicator: 'green',
          });
          d.hide();
          frm.reload_doc();
        }).catch(() => d.enable_primary_action());
      },
    });
    d.show();
  });
}

// =============================================================================
// Manual Reconciliation Dialogs (Phase A)
// =============================================================================

function _openMatchInvoicesDialog(frm, row) {
  if (!row.party_type || !row.party) {
    frappe.msgprint(__('Bitte zuerst eine Party (Mieter/Lieferant) zuweisen.'));
    return;
  }

  frappe.call({
    method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.get_open_invoices_for_row',
    args: { docname: frm.doc.name, row_name: row.name },
    freeze: true,
    freeze_message: __('Lade offene Rechnungen…'),
  }).then((r) => {
    const data = (r && r.message) || {};
    const invoices = data.invoices || [];
    const target = parseFloat(data.target_amount || row.betrag || 0);

    if (!invoices.length) {
      frappe.msgprint({
        title: __('Keine offenen Rechnungen'),
        message: __('Für {0} {1} sind keine offenen Rechnungen vorhanden. Nutze „Zahlung erstellen" für eine Vorauszahlung oder „Buchungssatz erstellen" für eine direkte GL-Buchung.', [row.party_type, row.party]),
      });
      return;
    }

    const fmt = (v) => frappe.format(v, { fieldtype: 'Currency' });
    const fmtDate = (v) => (v ? frappe.datetime.str_to_user(v) : '-');

    const rowsHtml = invoices.map((inv) => {
      const outstanding = parseFloat(inv.outstanding_amount).toFixed(2);
      const safeName = frappe.utils.escape_html(inv.name);
      const linkPath = data.invoice_doctype.toLowerCase().replace(/ /g, '-');
      return `
        <tr>
          <td style="padding:4px 8px;"><input type="checkbox" class="hv-inv-cb" data-name="${safeName}" data-outstanding="${outstanding}"></td>
          <td style="padding:4px 8px;"><a href="/app/${linkPath}/${encodeURIComponent(inv.name)}" target="_blank">${safeName}</a></td>
          <td style="padding:4px 8px; text-align:right; color:#888;">${fmt(inv.outstanding_amount)}</td>
          <td style="padding:4px 8px;">
            <input type="number" class="hv-inv-amount form-control input-sm" step="0.01" min="0" max="${outstanding}"
              data-name="${safeName}" data-outstanding="${outstanding}" disabled
              style="width:120px; text-align:right;" placeholder="0,00">
          </td>
          <td style="padding:4px 8px; white-space:nowrap;">${fmtDate(inv.posting_date)}</td>
        </tr>
      `;
    }).join('');

    const html = `
      <div style="margin-bottom:10px; padding:8px 10px; background:#f6f6f7; border-radius:4px; font-size:12px;">
        <strong>${__('Bank-Betrag')}:</strong> ${fmt(target)} &nbsp;•&nbsp;
        <strong>${__('Party')}:</strong> ${frappe.utils.escape_html(row.party)} (${frappe.utils.escape_html(row.party_type)})
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:12px;">
        <thead>
          <tr style="background:#f6f6f7;">
            <th style="padding:4px 8px; width:30px;"></th>
            <th style="padding:4px 8px; text-align:left;">${__('Rechnung')}</th>
            <th style="padding:4px 8px; text-align:right;">${__('Offen')}</th>
            <th style="padding:4px 8px; text-align:left;">${__('Zuweisen')}</th>
            <th style="padding:4px 8px; text-align:left;">${__('Datum')}</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
      <div style="margin-top:6px; font-size:11px; color:#888;">
        ${__('Tipp: Häkchen aktiviert die Zeile und füllt den maximal noch passenden Betrag vor — den kannst du anpassen, um Teilzahlungen abzubilden.')}
      </div>
      <div class="hv-match-summary" style="margin-top:14px; padding:10px 12px; background:#fff7ed; border:1px solid #fed7aa; border-radius:4px; font-size:13px; line-height:1.7;">
        <div><strong>${__('Summe ausgewählt')}:</strong> <span class="hv-sum"></span></div>
        <div><strong>${__('Bank-Betrag')}:</strong> ${fmt(target)}</div>
        <div><strong>${__('Differenz')}:</strong> <span class="hv-diff"></span> <span class="hv-diff-note" style="margin-left:8px; font-style:italic;"></span></div>
      </div>
      <div style="margin-top:10px;">
        <label style="font-size:12px;">
          <input type="checkbox" class="hv-leftover-cb">
          ${__('Restbetrag als Vorauszahlung verbuchen (bleibt am Mieter/Lieferant als offenes Guthaben)')}
        </label>
      </div>
    `;

    const d = new frappe.ui.Dialog({
      title: __('Rechnungen zuordnen — Zeile {0}', [row.idx]),
      size: 'large',
      fields: [{ fieldtype: 'HTML', fieldname: 'body', options: html }],
      primary_action_label: __('Zuordnen'),
      primary_action() {
        const allocations = [];
        let allocSum = 0;
        d.$wrapper.find('.hv-inv-cb:checked').each(function () {
          const name = $(this).attr('data-name');
          const amountInput = d.$wrapper.find('.hv-inv-amount[data-name="' + name + '"]');
          const allocated = parseFloat(amountInput.val()) || 0;
          if (allocated <= 0) return;  // Skip zero allocations
          const outstanding = parseFloat(amountInput.attr('data-outstanding')) || 0;
          if (allocated > outstanding + 0.01) {
            frappe.msgprint(__('Zuweisung für {0} ({1}) übersteigt offenen Betrag ({2}).', [
              name, frappe.format(allocated, { fieldtype: 'Currency' }), frappe.format(outstanding, { fieldtype: 'Currency' }),
            ]));
            allocations.length = 0;  // Abort
            return false;
          }
          allocations.push({ name, allocated_amount: allocated });
          allocSum += allocated;
        });
        if (!allocations.length) {
          frappe.msgprint(__('Bitte mindestens eine Rechnung mit Betrag > 0 auswählen.'));
          return;
        }
        const leftover = d.$wrapper.find('.hv-leftover-cb').is(':checked') ? 1 : 0;
        d.disable_primary_action();
        frappe.call({
          method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.manually_reconcile_row',
          args: {
            docname: frm.doc.name,
            row_name: row.name,
            invoice_names: JSON.stringify(allocations),
            leftover_as_advance: leftover,
          },
          freeze: true,
          freeze_message: __('Zuordnung wird gebucht…'),
        }).then((res) => {
          const msg = (res && res.message) || {};
          frappe.show_alert({
            message: __('Zugeordnet: {0} ({1} Rechnung(en))', [msg.payment_entry, (msg.invoices || []).length]),
            indicator: 'green',
          });
          d.hide();
          frm.reload_doc();
        }).catch(() => {
          d.enable_primary_action();
        });
      },
    });

    d.show();

    // Live-Sum-Update + Auto-Fill bei Checkbox-Aktivierung
    const recalc = () => {
      let sum = 0;
      d.$wrapper.find('.hv-inv-cb:checked').each(function () {
        const name = $(this).attr('data-name');
        const input = d.$wrapper.find('.hv-inv-amount[data-name="' + name + '"]');
        sum += parseFloat(input.val()) || 0;
      });
      const diff = target - sum;
      // Wichtig: .html() (nicht .text()), weil frappe.format() HTML zurückgibt
      d.$wrapper.find('.hv-sum').html(fmt(sum));
      d.$wrapper.find('.hv-diff').html(fmt(diff));
      const note = d.$wrapper.find('.hv-diff-note');
      const leftoverCb = d.$wrapper.find('.hv-leftover-cb');
      const primary = d.$wrapper.find('.modal-footer .btn-primary');
      if (Math.abs(diff) < 0.01) {
        note.css('color', '#15803d').text(__('exakt'));
        primary.prop('disabled', false);
      } else if (diff > 0) {
        note.css('color', '#92400e').text(leftoverCb.is(':checked') ? __('wird als Vorauszahlung verbucht') : __('Restbetrag offen'));
        primary.prop('disabled', !leftoverCb.is(':checked'));
      } else {
        note.css('color', '#dc3545').text(__('Auswahl übersteigt Bank-Betrag'));
        primary.prop('disabled', true);
      }
    };

    // Checkbox-Toggle: Input enablen/disablen, beim Aktivieren Beträge auto-füllen
    d.$wrapper.on('change', '.hv-inv-cb', function () {
      const name = $(this).attr('data-name');
      const input = d.$wrapper.find('.hv-inv-amount[data-name="' + name + '"]');
      if (this.checked) {
        input.prop('disabled', false);
        // Auto-Fill: noch fehlender Restbetrag bis target, aber max. outstanding der Zeile
        let currentSum = 0;
        d.$wrapper.find('.hv-inv-cb:checked').each(function () {
          if ($(this).attr('data-name') === name) return;
          const otherInput = d.$wrapper.find('.hv-inv-amount[data-name="' + $(this).attr('data-name') + '"]');
          currentSum += parseFloat(otherInput.val()) || 0;
        });
        const remaining = Math.max(0, target - currentSum);
        const outstanding = parseFloat(input.attr('data-outstanding')) || 0;
        const fillAmount = Math.min(outstanding, remaining);
        input.val(fillAmount.toFixed(2));
        input.focus().select();
      } else {
        input.prop('disabled', true);
        input.val('');
      }
      recalc();
    });
    d.$wrapper.on('input', '.hv-inv-amount', recalc);
    d.$wrapper.on('change', '.hv-leftover-cb', recalc);
    recalc();
  });
}

function _openAbschlagDialog(frm, row) {
  if (row.richtung !== 'Ausgang' || row.party_type !== 'Supplier' || !row.party) {
    frappe.msgprint(__('Abschlagsplan-Zuordnung ist nur für Lieferanten-Ausgänge möglich.'));
    return;
  }

  frappe.call({
    method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.get_abschlagsplan_candidates_for_row',
    args: { docname: frm.doc.name, row_name: row.name },
    freeze: true,
    freeze_message: __('Lade offene Abschlagsplan-Zeilen…'),
  }).then((r) => {
    const data = (r && r.message) || {};
    const candidates = data.candidates || [];
    const target = parseFloat(data.target_amount || row.betrag || 0);
    const fmt = (v) => frappe.format(v, { fieldtype: 'Currency' });
    const fmtDate = (v) => (v ? frappe.datetime.str_to_user(v) : '-');
    const escape = (v) => frappe.utils.escape_html(v || '-');

    if (!candidates.length) {
      frappe.msgprint({
        title: __('Keine passende Abschlagsplan-Zeile'),
        message: __('Es wurde keine offene Abschlagsplan-Zeile mit gleichem Lieferanten und Betrag gefunden. Prüfe Betrag, Bankkonto, Kostenstelle und Fälligkeitsdatum.'),
      });
      return;
    }

    const rowsHtml = candidates.map((c, idx) => {
      const safeRow = frappe.utils.escape_html(c.row_name);
      const delta = c.delta_days === null || c.delta_days === undefined ? '-' : `${c.delta_days} ${__('Tage')}`;
      const badges = [
        c.bank_account_match ? __('Bankkonto') : '',
        c.cost_center_match ? __('Kostenstelle') : '',
      ].filter(Boolean).join(' · ');
      return `
        <tr>
          <td style="padding:4px 8px;"><input type="radio" name="hv-abschlag-row" class="hv-abschlag-radio" value="${safeRow}" ${idx === 0 ? 'checked' : ''}></td>
          <td style="padding:4px 8px;"><a href="/app/zahlungsplan/${encodeURIComponent(c.zahlungsplan)}" target="_blank">${escape(c.zahlungsplan)}</a></td>
          <td style="padding:4px 8px;">${escape(c.bezeichnung)}</td>
          <td style="padding:4px 8px; text-align:right;">${fmt(c.betrag)}</td>
          <td style="padding:4px 8px; white-space:nowrap;">${fmtDate(c.faelligkeitsdatum)}</td>
          <td style="padding:4px 8px; text-align:right; color:#888;">${delta}</td>
          <td style="padding:4px 8px;">${escape(c.immobilie)}</td>
          <td style="padding:4px 8px;">${escape(badges)}</td>
        </tr>
      `;
    }).join('');

    const html = `
      <div style="margin-bottom:10px; padding:8px 10px; background:#f6f6f7; border-radius:4px; font-size:12px;">
        <strong>${__('Bank-Betrag')}:</strong> ${fmt(target)} &nbsp;•&nbsp;
        <strong>${__('Lieferant')}:</strong> ${escape(row.party)} &nbsp;•&nbsp;
        <strong>${__('Buchungstag')}:</strong> ${fmtDate(row.buchungstag)}
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:12px;">
        <thead>
          <tr style="background:#f6f6f7;">
            <th style="padding:4px 8px; width:30px;"></th>
            <th style="padding:4px 8px; text-align:left;">${__('Zahlungsplan')}</th>
            <th style="padding:4px 8px; text-align:left;">${__('Bezeichnung')}</th>
            <th style="padding:4px 8px; text-align:right;">${__('Betrag')}</th>
            <th style="padding:4px 8px; text-align:left;">${__('Fällig')}</th>
            <th style="padding:4px 8px; text-align:right;">${__('Abstand')}</th>
            <th style="padding:4px 8px; text-align:left;">${__('Immobilie')}</th>
            <th style="padding:4px 8px; text-align:left;">${__('Treffer')}</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
      <div style="margin-top:10px; font-size:12px; color:#666;">
        ${__('Es wird ein Payment Entry ohne Rechnung erstellt, mit der Bank Transaction abgeglichen und an die gewählte Abschlagsplan-Zeile gehängt.')}
      </div>
    `;

    const d = new frappe.ui.Dialog({
      title: __('Abschlag zuordnen — Zeile {0}', [row.idx]),
      size: 'large',
      fields: [{ fieldtype: 'HTML', fieldname: 'body', options: html }],
      primary_action_label: __('Zuordnen'),
      primary_action() {
        const selected = d.$wrapper.find('.hv-abschlag-radio:checked').val();
        if (!selected) {
          frappe.msgprint(__('Bitte eine Abschlagsplan-Zeile auswählen.'));
          return;
        }
        d.disable_primary_action();
        frappe.call({
          method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.assign_abschlagsplan_row',
          args: {
            docname: frm.doc.name,
            row_name: row.name,
            plan_row_name: selected,
            remarks: row.verwendungszweck || row.auftraggeber || '',
          },
          freeze: true,
          freeze_message: __('Abschlag wird gebucht…'),
        }).then((res) => {
          const msg = (res && res.message) || {};
          frappe.show_alert({
            message: __('Abschlag zugeordnet: {0} Zeile {1}', [msg.zahlungsplan, msg.row_idx]),
            indicator: 'green',
          });
          d.hide();
          frm.reload_doc();
        }).catch(() => {
          d.enable_primary_action();
        });
      },
    });
    d.show();
  });
}

function _openStandalonePaymentDialog(frm, row) {
  const fmt = (v) => frappe.format(v, { fieldtype: 'Currency' });

  const d = new frappe.ui.Dialog({
    title: __('Zahlung erstellen — Zeile {0}', [row.idx]),
    fields: [
      {
        fieldtype: 'HTML',
        fieldname: 'header',
        options: `<div style="margin-bottom:10px; font-size:12px; color:#666;">
          ${__('Erstellt ein Payment Entry über den vollen Bank-Betrag')} <strong>${fmt(row.betrag)}</strong>
          ${__('— ohne Verknüpfung zu einer Rechnung. Bleibt als Guthaben/Verbindlichkeit am Mieter/Lieferant offen.')}
        </div>`,
      },
      {
        fieldtype: 'Select',
        fieldname: 'party_type',
        label: __('Party Typ'),
        options: 'Customer\nSupplier',
        default: row.party_type || (row.richtung === 'Ausgang' ? 'Supplier' : 'Customer'),
        reqd: 1,
      },
      {
        fieldtype: 'Dynamic Link',
        fieldname: 'party',
        label: __('Party'),
        options: 'party_type',
        default: row.party || '',
        reqd: 1,
      },
      {
        fieldtype: 'Small Text',
        fieldname: 'remarks',
        label: __('Bemerkung'),
        default: row.verwendungszweck || row.auftraggeber || '',
      },
    ],
    primary_action_label: __('Buchen'),
    primary_action(values) {
      d.disable_primary_action();
      frappe.call({
        method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.create_standalone_payment_for_row',
        args: {
          docname: frm.doc.name,
          row_name: row.name,
          party_type: values.party_type,
          party: values.party,
          remarks: values.remarks || '',
        },
        freeze: true,
        freeze_message: __('Zahlung wird gebucht…'),
      }).then((res) => {
        const msg = (res && res.message) || {};
        frappe.show_alert({
          message: __('Payment Entry erstellt: {0}', [msg.payment_entry]),
          indicator: 'green',
        });
        d.hide();
        frm.reload_doc();
      }).catch(() => {
        d.enable_primary_action();
      });
    },
  });
  d.show();
}

function _openJournalEntryDialog(frm, row) {
  const fmt = (v) => frappe.format(v, { fieldtype: 'Currency' });
  const isEingang = row.richtung === 'Eingang';
  const target = parseFloat(row.betrag) || 0;

  const html = `
    <div style="margin-bottom:10px; font-size:12px; color:#666;">
      ${__('Erstellt einen Journal Entry')} <strong>${fmt(target)}</strong>
      ${isEingang ? __('(Bank Soll, Gegenkonten Haben)') : __('(Bank Haben, Gegenkonten Soll)')}.
      ${__('Mehrere Zeilen erlaubt — z.B. Hauptbetrag + Bankgebühr in einem Vorgang.')}
    </div>
    <table class="table table-sm" style="margin-bottom:6px; table-layout:fixed;">
      <colgroup>
        <col style="width:42%;">
        <col style="width:30%;">
        <col style="width:20%;">
        <col style="width:8%;">
      </colgroup>
      <thead>
        <tr>
          <th>${__('Gegenkonto')}</th>
          <th>${__('Kostenstelle')}</th>
          <th style="text-align:right;">${__('Betrag')}</th>
          <th></th>
        </tr>
      </thead>
      <tbody class="hv-je-rows"></tbody>
    </table>
    <div style="margin-bottom:10px;">
      <button type="button" class="btn btn-xs btn-default hv-je-add">+ ${__('Zeile')}</button>
    </div>
    <div class="hv-je-summary" style="margin-top:8px; padding:10px 12px; background:#fff7ed; border:1px solid #fed7aa; border-radius:4px; font-size:13px; line-height:1.7;">
      <div><strong>${__('Summe Splits')}:</strong> <span class="hv-sum"></span></div>
      <div><strong>${__('Bank-Betrag')}:</strong> ${fmt(target)}</div>
      <div><strong>${__('Differenz')}:</strong> <span class="hv-diff"></span> <span class="hv-diff-note" style="margin-left:8px; font-style:italic;"></span></div>
    </div>
  `;

  const d = new frappe.ui.Dialog({
    title: __('Buchungssatz erstellen — Zeile {0}', [row.idx]),
    size: 'large',
    fields: [
      { fieldtype: 'HTML', fieldname: 'body', options: html },
      {
        fieldtype: 'Small Text',
        fieldname: 'remarks',
        label: __('Bemerkung'),
        default: row.verwendungszweck || row.auftraggeber || '',
      },
    ],
    primary_action_label: __('Buchen'),
    primary_action(values) {
      const splits = collectSplits();
      if (!splits.ok) {
        frappe.msgprint(splits.error);
        return;
      }
      d.disable_primary_action();
      frappe.call({
        method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.create_journal_entry_for_row',
        args: {
          docname: frm.doc.name,
          row_name: row.name,
          splits: JSON.stringify(splits.list),
          remarks: values.remarks || '',
        },
        freeze: true,
        freeze_message: __('Buchungssatz wird gebucht…'),
      }).then((res) => {
        const msg = (res && res.message) || {};
        frappe.show_alert({
          message: __('Buchungssatz erstellt: {0}', [msg.journal_entry]),
          indicator: 'green',
        });
        d.hide();
        frm.reload_doc();
      }).catch(() => {
        d.enable_primary_action();
      });
    },
  });

  d.show();

  const $rows = d.$wrapper.find('.hv-je-rows');
  const splitControls = []; // { tr, accountControl, costCenterControl, amountInput }
  let defaultCostCenter = '';

  const recalc = () => {
    let sum = 0;
    splitControls.forEach((sc) => {
      sum += parseFloat(sc.amountInput.val()) || 0;
    });
    const diff = target - sum;
    d.$wrapper.find('.hv-sum').html(fmt(sum));
    d.$wrapper.find('.hv-diff').html(fmt(diff));
    const note = d.$wrapper.find('.hv-diff-note');
    const primary = d.$wrapper.find('.modal-footer .btn-primary');
    if (Math.abs(diff) < 0.01) {
      note.css('color', '#15803d').text(__('exakt'));
      primary.prop('disabled', false);
    } else if (diff > 0) {
      note.css('color', '#92400e').text(__('Restbetrag offen'));
      primary.prop('disabled', true);
    } else {
      note.css('color', '#dc3545').text(__('Summe übersteigt Bank-Betrag'));
      primary.prop('disabled', true);
    }
  };

  const collectSplits = () => {
    const list = [];
    for (const sc of splitControls) {
      const acc = (sc.accountControl.get_value && sc.accountControl.get_value()) || '';
      const amt = parseFloat(sc.amountInput.val()) || 0;
      if (!acc && amt <= 0) continue; // Leere Zeile überspringen
      if (!acc) {
        return { ok: false, error: __('Zeile ohne Konto.') };
      }
      if (amt <= 0) {
        return { ok: false, error: __('Zeile {0}: Betrag muss > 0 sein.', [acc]) };
      }
      const cc = (sc.costCenterControl.get_value && sc.costCenterControl.get_value()) || '';
      list.push({ account: acc, cost_center: cc || null, amount: amt });
    }
    if (!list.length) {
      return { ok: false, error: __('Bitte mindestens eine Zeile mit Konto und Betrag erfassen.') };
    }
    const sum = list.reduce((s, x) => s + x.amount, 0);
    if (Math.abs(sum - target) > 0.01) {
      return {
        ok: false,
        error: __('Summe ({0}) stimmt nicht mit Bank-Betrag ({1}) überein.', [fmt(sum), fmt(target)]),
      };
    }
    return { ok: true, list };
  };

  const addSplitRow = ({ account = '', cost_center = '', amount = '' } = {}) => {
    const tr = $(`
      <tr>
        <td class="hv-je-account-cell"></td>
        <td class="hv-je-cc-cell"></td>
        <td><input type="number" step="0.01" min="0" class="form-control input-sm hv-je-amount" style="text-align:right;"></td>
        <td style="text-align:right;"><button type="button" class="btn btn-xs btn-default hv-je-remove" title="${__('Zeile entfernen')}">&times;</button></td>
      </tr>
    `);
    $rows.append(tr);

    const accountControl = frappe.ui.form.make_control({
      df: { fieldtype: 'Link', options: 'Account', placeholder: __('Konto') },
      parent: tr.find('.hv-je-account-cell').get(0),
      render_input: true,
    });
    accountControl.refresh_input && accountControl.refresh_input();
    if (account) accountControl.set_value(account);

    const costCenterControl = frappe.ui.form.make_control({
      df: { fieldtype: 'Link', options: 'Cost Center', placeholder: __('Kostenstelle') },
      parent: tr.find('.hv-je-cc-cell').get(0),
      render_input: true,
    });
    costCenterControl.refresh_input && costCenterControl.refresh_input();
    const initialCc = cost_center || defaultCostCenter;
    if (initialCc) costCenterControl.set_value(initialCc);

    const amountInput = tr.find('.hv-je-amount');
    if (amount !== '' && amount !== null && amount !== undefined) amountInput.val(amount);

    amountInput.on('input', recalc);

    tr.find('.hv-je-remove').on('click', () => {
      const idx = splitControls.findIndex((sc) => sc.tr.is(tr));
      if (idx >= 0) splitControls.splice(idx, 1);
      tr.remove();
      if (!splitControls.length) addSplitRow({ amount: target });
      recalc();
    });

    splitControls.push({ tr, accountControl, costCenterControl, amountInput });
    recalc();
    return splitControls[splitControls.length - 1];
  };

  d.$wrapper.find('.hv-je-add').on('click', () => addSplitRow());

  // Erste Zeile mit Vollbetrag, Kostenstelle aus Immobilie der BT vorbelegen
  frappe.call({
    method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.get_expected_cost_center_for_row',
    args: { docname: frm.doc.name, row_name: row.name },
  }).then((r) => {
    defaultCostCenter = (r && r.message && r.message.cost_center) || '';
    addSplitRow({ amount: target });
  }).catch(() => {
    addSplitRow({ amount: target });
  });
}

function _assignExistingParty(frm, row, partyType) {
  const labelMap = { Customer: __('Mieter'), Supplier: __('Lieferant'), Eigentuemer: __('Eigentümer') };
  const label = labelMap[partyType] || partyType;
  const d = new frappe.ui.Dialog({
    title: __('{0} zuweisen', [label]),
    fields: [
      {
        fieldtype: 'Link',
        fieldname: 'party',
        label: label,
        options: partyType,
        reqd: 1,
        default: row.party_type === partyType ? row.party : '',
      },
      {
        fieldtype: 'Data',
        fieldname: 'iban',
        label: __('IBAN'),
        default: row.iban || '',
        description: __('Wird als Bank-Account-Verknüpfung am Mieter/Lieferant hinterlegt, falls noch nicht vorhanden.'),
      },
    ],
    primary_action_label: __('Zuweisen'),
    primary_action(values) {
      if (!values.party) return;
      d.hide();
      frappe.call({
        method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.apply_party_to_row_and_relink',
        args: {
          docname: frm.doc.name,
          row_name: row.name,
          party_type: partyType,
          party: values.party,
          iban: values.iban || '',
        },
        freeze: true,
        freeze_message: __('Wird zugewiesen…'),
      }).then((r) => {
        const msg = (r && r.message) || {};
        const ba = msg.bank_account || {};
        const more = (msg.relink_all_count || 0) + (msg.relink_bt_count || 0);
        const tail = more ? __(' Auch {0} weitere Zeile(n).', [more]) : '';
        const baTail = ba.created ? __(' Bankkonto angelegt.') : '';
        frappe.show_alert({
          message: __('{0} {1} zugewiesen.', [label, values.party]) + baTail + tail,
          indicator: 'green',
        });
        frm.reload_doc();
      });
    },
  });
  d.show();

  // Kostenstelle aus der Immobilie der BT vorbelegen (User kann überschreiben)
  frappe.call({
    method: 'hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.get_expected_cost_center_for_row',
    args: { docname: frm.doc.name, row_name: row.name },
  }).then((r) => {
    const cc = r && r.message && r.message.cost_center;
    if (cc) d.set_value('cost_center', cc);
  });
}

frappe.ui.form.on('Bankauszug Import Row', {
  aktionen(frm, cdt, cdn) {
    const row = frappe.get_doc(cdt, cdn);
    if (row) _openRowActions(frm, row);
  },
  prepare_customer(frm, cdt, cdn) {
    const row = frappe.get_doc(cdt, cdn);
    if (row) _prepareCustomer(frm, row);
  },
  prepare_supplier(frm, cdt, cdn) {
    const row = frappe.get_doc(cdt, cdn);
    if (row) _prepareSupplier(frm, row);
  },
  prepare_bank_account(frm, cdt, cdn) {
    const row = frappe.get_doc(cdt, cdn);
    if (row) _prepareBankAccount(frm, row);
  },
});

// Status-Sort-Reihenfolge: Probleme zuerst (failed/leer/missing), dann success/vorhanden.
const _STATUS_ORDER = {
  'failed':           0,
  '':                 1,  // unverarbeitet
  'schon vorhanden':  2,
  'success':          3,
};

function sortRowsByStatus(frm) {
  const rows = frm.doc.rows || [];
  rows.sort((a, b) => {
    const sa = _STATUS_ORDER[(a.row_status || '').trim()] ?? 99;
    const sb = _STATUS_ORDER[(b.row_status || '').trim()] ?? 99;
    if (sa !== sb) return sa - sb;
    // Innerhalb gleicher Status-Gruppe: Probleme (kein party) zuerst
    const pa = a.party ? 1 : 0;
    const pb = b.party ? 1 : 0;
    if (pa !== pb) return pa - pb;
    return (a.idx || 0) - (b.idx || 0);
  });
  rows.forEach((r, i) => { r.idx = i + 1; });
  frm.doc.rows = rows;
  frm.refresh_field('rows');
  frappe.show_alert({ message: __('Nach Status sortiert (Probleme zuerst).'), indicator: 'blue' });
}

function sortRowsByBuchungstag(frm) {
  const rows = frm.doc.rows || [];
  rows.sort((a, b) => {
    const da = (a.buchungstag || '');
    const db = (b.buchungstag || '');
    return da.localeCompare(db);
  });
  rows.forEach((r, i) => { r.idx = i + 1; });
  frm.doc.rows = rows;
  frm.refresh_field('rows');
  frappe.show_alert({ message: __('Nach Buchungstag sortiert.'), indicator: 'blue' });
}
