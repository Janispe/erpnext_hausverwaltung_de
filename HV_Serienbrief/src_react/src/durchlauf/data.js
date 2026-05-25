// Sample data for the Serienbrief Durchlauf prototype

export const DURCHLAUF = {
  id: "SBDL-2026-00042",
  title: "Mahnlauf Mai 2026 — Tristanstr. 4",
  status: "draft", // draft | running | completed | failed | sent
  vorlage: { id: "TPL-MAHN-001", title: "1. Mahnung", kategorie: "Mahnungen" },
  iteration_doctype: "Mietvertrag",
  date: "2026-05-25",
  created_by: "j.peters@example.de",
  created: "2026-05-25T09:14:00",
  // Template variables (overridable per Durchlauf)
  variables: [
    { name: "frist_tage", type: "Zahl", default: "14", value: "14", desc: "Zahlungsfrist in Tagen" },
    { name: "stichtag", type: "Datum", default: "", value: "2026-06-08", desc: "Fälligkeitsdatum" },
    { name: "mahngebuehr", type: "Zahl", default: "5,00", value: "5,00", desc: "Mahngebühr in Euro" },
  ],
};

// Recipients (Iterationsobjekte) — Mietverträge mit Saldo
export const RECIPIENTS = [
  {
    id: "MV-2024-0142", customer: "Müller, Andreas",
    address: "Tristanstr. 4, WE 03 · 80637 München",
    saldo: "–847,32 €", mahnstufe: 1,
    email: "a.mueller@example.de", has_email: true,
    status: "generated", pages: 1, render_ms: 1240,
    generated_at: "2026-05-25T09:16:21",
    pdf_ok: true, missing_vars: [],
  },
  {
    id: "MV-2023-0098", customer: "Schäfer, Marlene",
    address: "Tristanstr. 4, WE 07 · 80637 München",
    saldo: "0,00 €", mahnstufe: 0,
    email: "m.schaefer@example.de", has_email: true,
    status: "skipped", pages: 0, render_ms: 0,
    skip_reason: "Saldo = 0 €",
    pdf_ok: false, missing_vars: [],
  },
  {
    id: "MV-2021-0034", customer: "Bauer, Reinhold",
    address: "Leopoldstr. 88, WE 12 · 80802 München",
    saldo: "–2.412,55 €", mahnstufe: 2,
    email: null, has_email: false,
    status: "generated", pages: 2, render_ms: 1820,
    generated_at: "2026-05-25T09:16:23",
    pdf_ok: true, missing_vars: [],
    warning: "Mahnstufe 2 — Mahngebühren-Klausel aktiv",
  },
  {
    id: "MV-2022-0211", customer: "Köhler, Petra",
    address: "Tristanstr. 4, WE 11 · 80637 München",
    saldo: "–134,50 €", mahnstufe: 1,
    email: "p.koehler@example.de", has_email: true,
    status: "generated", pages: 1, render_ms: 1180,
    generated_at: "2026-05-25T09:16:24",
    pdf_ok: true, missing_vars: [],
  },
  {
    id: "MV-2020-0078", customer: "Voss, Heinrich",
    address: "Leopoldstr. 88, WE 03 · 80802 München",
    saldo: "–589,00 €", mahnstufe: 1,
    email: "h.voss@example.de", has_email: true,
    status: "error", pages: 0, render_ms: 0,
    pdf_ok: false,
    error_msg: "Bankverbindung nicht hinterlegt — Baustein „Fußzeile Bankverbindung\" hat keinen Pfad.",
  },
  {
    id: "MV-2024-0203", customer: "Richter, Anna",
    address: "Tristanstr. 4, WE 09 · 80637 München",
    saldo: "–212,80 €", mahnstufe: 1,
    email: "a.richter@example.de", has_email: true,
    status: "generated", pages: 1, render_ms: 1310,
    generated_at: "2026-05-25T09:16:25",
    pdf_ok: true, missing_vars: [],
  },
  {
    id: "MV-2023-0156", customer: "Klein, Tobias",
    address: "Schellingstr. 22, WE 04 · 80799 München",
    saldo: "–1.024,00 €", mahnstufe: 1,
    email: "t.klein@example.de", has_email: true,
    status: "pending", pages: 0, render_ms: 0,
    pdf_ok: false,
  },
  {
    id: "MV-2025-0019", customer: "Hartmann, Sabine",
    address: "Schellingstr. 22, WE 11 · 80799 München",
    saldo: "–345,00 €", mahnstufe: 1,
    email: null, has_email: false,
    status: "generated", pages: 1, render_ms: 1090,
    generated_at: "2026-05-25T09:16:26",
    pdf_ok: true, missing_vars: ["bankkonto.iban"],
    warning: "Optionaler Platzhalter `bankkonto.iban` ist leer — wird ausgeblendet.",
  },
  {
    id: "MV-2022-0145", customer: "Lange, Friedrich",
    address: "Leopoldstr. 88, WE 17 · 80802 München",
    saldo: "–678,90 €", mahnstufe: 1,
    email: "f.lange@example.de", has_email: true,
    status: "generated", pages: 1, render_ms: 1220,
    generated_at: "2026-05-25T09:16:27",
    pdf_ok: true, missing_vars: [],
  },
  {
    id: "MV-2024-0119", customer: "Werner, Julia",
    address: "Tristanstr. 4, WE 15 · 80637 München",
    saldo: "–489,15 €", mahnstufe: 1,
    email: "j.werner@example.de", has_email: true,
    status: "generated", pages: 1, render_ms: 1170,
    generated_at: "2026-05-25T09:16:28",
    pdf_ok: true, missing_vars: [],
  },
  {
    id: "MV-2023-0211", customer: "Brandt, Klaus",
    address: "Schellingstr. 22, WE 07 · 80799 München",
    saldo: "–98,40 €", mahnstufe: 1,
    email: "k.brandt@example.de", has_email: true,
    status: "generated", pages: 1, render_ms: 1100,
    generated_at: "2026-05-25T09:16:29",
    pdf_ok: true, missing_vars: [],
  },
  {
    id: "MV-2021-0167", customer: "Vogel, Daniela",
    address: "Leopoldstr. 88, WE 05 · 80802 München",
    saldo: "–1.560,00 €", mahnstufe: 2,
    email: "d.vogel@example.de", has_email: true,
    status: "generated", pages: 2, render_ms: 1750,
    generated_at: "2026-05-25T09:16:30",
    pdf_ok: true, missing_vars: [],
    warning: "Mahnstufe 2 — Mahngebühren-Klausel aktiv",
  },
];

// Available Mietverträge to add (not yet in list)
export const AVAILABLE = [
  { id: "MV-2022-0033", customer: "Sommer, Max", address: "Tristanstr. 4, WE 01", saldo: "0,00 €" },
  { id: "MV-2023-0145", customer: "Engel, Maria", address: "Tristanstr. 4, WE 17", saldo: "–67,00 €" },
  { id: "MV-2024-0078", customer: "Krause, Peter", address: "Leopoldstr. 88, WE 09", saldo: "0,00 €" },
];

