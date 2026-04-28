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
      frm.add_custom_button('Nur Problemzeilen', () => applyRowFilter(frm, 'problems'), 'Filter');
      frm.add_custom_button('Nur ohne Party', () => applyRowFilter(frm, 'missing_party'), 'Filter');
      frm.add_custom_button('Nur ohne Bank Transaction', () => applyRowFilter(frm, 'missing_bank_transaction'), 'Filter');
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
  const allHaveParty = rows.every(r => r.party_type && r.party);
  const allHaveBT    = rows.every(r => r.bank_transaction || r.reference);
  if (allHaveBT)     return 'done';
  if (allHaveParty)  return 'phase2';
  return 'phase1';
}

function _renderInfoBanner(frm) {
  const rows = frm.doc.rows || [];
  const total     = rows.length;
  const withParty = rows.filter(r => r.party_type && r.party).length;
  const withoutParty = total - withParty;
  const withBT    = rows.filter(r => r.bank_transaction || r.reference).length;
  const withoutBT = total - withBT;
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
    phase1: { bg: '#fff4e5', fg: '#92400e', border: '#fdba74', icon: '①', title: __('Phase 1 von 2 — Parties zuordnen') },
    phase2: { bg: '#e6f0ff', fg: '#0c4a8b', border: '#7eb1ed', icon: '②', title: __('Phase 2 von 2 — Bank-Transaktionen erstellen') },
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
    if (success)   pills += pill('green',  __('{0} ✓ erstellt', [success]));
    if (vorhanden) pills += pill('gray',   __('{0} bereits vorhanden', [vorhanden]));
    if (failed)    pills += pill('red',    __('{0} Fehler', [failed]));
    if (withoutBT && phase === 'phase2') pills += pill('orange', __('{0} bereit zum Buchen', [withoutBT]));
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
    const handler = function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
      const $row = $(this).closest('.grid-row');
      const cdn = $row.attr('data-name');
      if (!cdn) return false;
      const row = frappe.get_doc('Bankauszug Import Row', cdn);
      if (row) _openRowActions(frm, row);
      return false;
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
  // phase2 / done
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
          const msg2 = (res2 && res2.message) || {};
          const { created = [], errors = [], created_without_party = 0 } = msg2;
          let summary = `Erstellt: ${created.length}`;
          if (errors.length) summary += `, Fehler: ${errors.length}`;
          if (created_without_party) summary += `, Ohne Party: ${created_without_party}`;
          frappe.msgprint(summary);
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
    const { created = [], errors = [], created_without_party = 0 } = msg;
    let summary = `Erstellt: ${created.length}`;
    if (errors.length) summary += `, Fehler: ${errors.length}`;
    if (created_without_party) summary += `, Ohne Party: ${created_without_party}`;
    frappe.msgprint(summary);
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
  if (mode === 'problems') {
    // Phase 1: Probleme = fehlende Partei (das ist hier der Hauptfokus).
    // Phase 2/done: Probleme = failed-Status, Error, oder noch ohne Bank-Transaktion.
    if (phase === 'phase1') {
      return !(row.party_type && row.party);
    }
    if (row.row_status === 'failed') return true;
    if ((row.error || '').toString().trim()) return true;
    if (!(row.bank_transaction || row.reference)) return true;
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
