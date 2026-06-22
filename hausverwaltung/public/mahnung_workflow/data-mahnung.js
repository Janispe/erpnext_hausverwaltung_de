// data-mahnung.js — Datengrundlage für den Mahnung-Editor (ERPNext "Dunning"-Objekt).
// Self-contained: lädt NICHT data-op.js / data.js. Mehrere Mieter für den Switcher,
// pro Mieter mehrere überfällige Sales Invoices, Mahnhistorie und Dunning-Vorlagen.

(function () {
  const TODAY = "2026-05-27";

  const daysBetween = (a, b) => {
    const d1 = new Date(a), d2 = new Date(b);
    return Math.round((d2 - d1) / 86400000);
  };
  const overdueDays = (faellig) => (faellig ? Math.max(0, daysBetween(faellig, TODAY)) : 0);

  // ── Absender (Hausverwaltung) ─────────────────────────────────────────────
  const absender = {
    firma: "Hausverwaltung Müller GmbH",
    strasse: "Hauptstraße 1",
    plz_ort: "70173 Stuttgart",
    telefon: "0711 / 24 80 19-0",
    email: "buchhaltung@hv-mueller.de",
    ust: "DE 812 345 678",
    geschaeftsfuehrer: "Dipl.-Kfm. Andreas Müller",
    sachbearbeiter: "Frau Petra Lang",
    bank: "Baden-Württembergische Bank",
    iban: "DE21 6005 0101 0001 2345 67",
    bic: "SOLADEST600",
    konto_forderungen: "1400 — Forderungen Mieter",
    konto_erloese_mahn: "8950 — Mahngebühren-Erlöse",
  };

  // ── Mieter mit überfälligen Posten ─────────────────────────────────────────
  // verbrauchertyp: "privat" → §288 Abs.1 (5 %-Punkte über Basiszins),
  //                 "gewerbe" → §288 Abs.2 (9 %-Punkte über Basiszins).
  const inv = (o) => ({
    ...o,
    art: o.art || "Sales Invoice",
    bezahlt: o.bezahlt || 0,
    posting: o.posting || o.faellig,
    overdue_days: overdueDays(o.faellig),
  });

  const mieter = [
    {
      id: "DEB-2024-00102",
      anrede: "Sehr geehrte Familie Albrecht,",
      name: "Familie Albrecht",
      adresse: ["Familie Albrecht", "Kirchgasse 12", "70173 Stuttgart"],
      objekt: "Kirchgasse 12, 70173 Stuttgart",
      einheit: "1. OG rechts · Whg. 5",
      kostenstelle: "Kirchgasse 12",
      email: "albrecht.familie@email.de",
      verbrauchertyp: "privat",
      mahnstufe: 2,
      empf_vorlage: "letzte_mahnung",
      historie: [
        { datum: "2026-03-12", stufe: "Zahlungserinnerung", vorlageKey: "erinnerung", beleg: "DUN-2026-0041", kanal: "Brief",
          status: "Gebucht · offen", frist: "2026-03-22",
          belege: [{ beleg: "ACC-SINV-2026-00115", betrag: 980.00 }],
          hauptforderung: 980.00, zinsBetrag: 0, gebuehr: 0, summe: 980.00,
          docs: [{ id: "DUN-2026-0041", desc: "Dunning-Doc · Zahlungserinnerung", amount: 980.00 }, { id: "Mahnung-0041.pdf", desc: "PDF-Anhang · Brief", amount: null }] },
        { datum: "2026-04-02", stufe: "1. Mahnung", vorlageKey: "mahnung_1", beleg: "DUN-2026-0067", kanal: "Brief",
          status: "Gebucht · offen", frist: "2026-04-12",
          belege: [{ beleg: "ACC-SINV-2026-00115", betrag: 980.00 }, { beleg: "ACC-SINV-2026-00128", betrag: 980.00 }],
          hauptforderung: 1960.00, zinsBetrag: 8.20, gebuehr: 5.00, summe: 1973.20,
          docs: [{ id: "DUN-2026-0067", desc: "Dunning-Doc · 1. Mahnung", amount: 1973.20 }, { id: "ACC-JV-2026-00094", desc: "Journal Entry · Mahngebühr (8950)", amount: 5.00 }, { id: "Mahnung-0067.pdf", desc: "PDF-Anhang · Brief", amount: null }] },
        { datum: "2026-05-12", stufe: "2. Mahnung", vorlageKey: "mahnung_2", beleg: "DUN-2026-0090", kanal: "Brief + E-Mail",
          status: "Gebucht · offen", frist: "2026-05-22",
          belege: [{ beleg: "ACC-SINV-2026-00115", betrag: 980.00 }, { beleg: "ACC-SINV-2026-00128", betrag: 980.00 }, { beleg: "ACC-SINV-2026-00141", betrag: 980.00 }],
          hauptforderung: 2940.00, zinsBetrag: 22.40, gebuehr: 10.00, summe: 2972.40,
          docs: [{ id: "DUN-2026-0090", desc: "Dunning-Doc · 2. Mahnung", amount: 2972.40 }, { id: "ACC-JV-2026-00101", desc: "Journal Entry · Mahngebühr (8950)", amount: 10.00 }, { id: "Mahnung-0090.pdf", desc: "PDF-Anhang · Brief + E-Mail", amount: null }] },
      ],
      posten: [
        inv({ beleg: "ACC-SINV-2026-00115", bez: "Mietabrechnung 03/2026 (Miete + BK + HK)", faellig: "2026-03-03", betrag: 980.00, offen: 980.00 }),
        inv({ beleg: "ACC-SINV-2026-00128", bez: "Mietabrechnung 04/2026 (Miete + BK + HK)", faellig: "2026-04-03", betrag: 980.00, offen: 980.00 }),
        inv({ beleg: "ACC-SINV-2026-00141", bez: "Mietabrechnung 05/2026 (Miete + BK + HK)", faellig: "2026-05-03", betrag: 980.00, offen: 980.00 }),
      ],
    },
    {
      id: "DEB-2024-00147",
      anrede: "Sehr geehrte Frau Hofmann,",
      name: "Sandra Hofmann",
      adresse: ["Frau Sandra Hofmann", "Hauptstraße 47", "70173 Stuttgart"],
      objekt: "Hauptstr. 47, 70173 Stuttgart",
      einheit: "3. OG links · Whg. 7",
      kostenstelle: "Hauptstr. 47",
      email: "s.hofmann@email.de",
      verbrauchertyp: "privat",
      mahnstufe: 1,
      empf_vorlage: "mahnung_2",
      historie: [
        { datum: "2026-05-12", stufe: "1. Mahnung", vorlageKey: "mahnung_1", beleg: "DUN-2026-0089", kanal: "Brief",
          status: "Gebucht · teilw. bezahlt", frist: "2026-05-22",
          belege: [{ beleg: "ACC-SINV-2026-00203", betrag: 1000.00 }],
          hauptforderung: 1000.00, zinsBetrag: 1.40, gebuehr: 5.00, summe: 1006.40,
          docs: [{ id: "DUN-2026-0089", desc: "Dunning-Doc · 1. Mahnung", amount: 1006.40 }, { id: "ACC-JV-2026-00091", desc: "Journal Entry · Mahngebühr (8950)", amount: 5.00 }, { id: "Mahnung-0089.pdf", desc: "PDF-Anhang · Brief", amount: null }] },
      ],
      posten: [
        inv({ beleg: "ACC-SINV-2026-00203", bez: "Mietabrechnung 05/2026 — Teilzahlung offen", faellig: "2026-05-03", betrag: 1000.00, bezahlt: 600.00, offen: 400.00 }),
        inv({ beleg: "ACC-JV-2026-00091", art: "Journal Entry", bez: "Mahngebühr 1. Mahnstufe", faellig: "2026-05-22", betrag: 5.00, offen: 5.00 }),
      ],
    },
    {
      id: "DEB-2024-00188",
      anrede: "Sehr geehrte Damen und Herren,",
      name: "Aydin GmbH (Gewerbe EG)",
      adresse: ["Aydin GmbH", "z. Hd. Geschäftsführung", "Mozartstraße 8", "70173 Stuttgart"],
      objekt: "Mozartstr. 8, 70173 Stuttgart",
      einheit: "Gewerbeeinheit EG",
      kostenstelle: "Mozartstr. 8",
      email: "verwaltung@aydin-gmbh.de",
      verbrauchertyp: "gewerbe",
      mahnstufe: 3,
      empf_vorlage: "letzte_mahnung",
      historie: [
        { datum: "2026-04-01", stufe: "1. Mahnung", vorlageKey: "mahnung_1", beleg: "DUN-2026-0061", kanal: "Brief",
          status: "Gebucht · offen", frist: "2026-04-11",
          belege: [{ beleg: "ACC-SINV-2026-00098", betrag: 1284.50 }],
          hauptforderung: 1284.50, zinsBetrag: 4.50, gebuehr: 5.00, summe: 1294.00,
          docs: [{ id: "DUN-2026-0061", desc: "Dunning-Doc · 1. Mahnung", amount: 1294.00 }, { id: "ACC-JV-2026-00072", desc: "Journal Entry · Mahngebühr (8950)", amount: 5.00 }, { id: "Mahnung-0061.pdf", desc: "PDF-Anhang · Brief", amount: null }] },
        { datum: "2026-04-22", stufe: "2. Mahnung", vorlageKey: "mahnung_2", beleg: "DUN-2026-0078", kanal: "Einschreiben",
          status: "Gebucht · offen", frist: "2026-05-02",
          belege: [{ beleg: "ACC-SINV-2026-00098", betrag: 1284.50 }],
          hauptforderung: 1284.50, zinsBetrag: 11.20, gebuehr: 10.00, summe: 1305.70,
          docs: [{ id: "DUN-2026-0078", desc: "Dunning-Doc · 2. Mahnung", amount: 1305.70 }, { id: "ACC-JV-2026-00083", desc: "Journal Entry · Mahngebühr (8950)", amount: 10.00 }, { id: "Mahnung-0078.pdf", desc: "PDF-Anhang · Einschreiben", amount: null }] },
      ],
      posten: [
        inv({ beleg: "ACC-SINV-2026-00098", bez: "Betriebskostenabrechnung 2025 — Nachzahlung", faellig: "2026-03-17", betrag: 1284.50, offen: 1284.50 }),
      ],
    },
  ];

  // ── Mahn-Vorlagen = Serienbrief-Vorlagen, Kategorie „Mahnungen" ─────────────
  // Quelle: HV_Serienbrief (TEMPLATE_TREE → "Mahnungen"). Man WÄHLT eine fertige
  // Vorlage aus der Bibliothek; sie bringt Text + Jinja-Platzhalter + Variablen mit.
  // Platzhalter im Text: {mieter} {objekt} {betrag} {frist} {stufe} {zweck} {sachbearbeiter} {firma}
  const BASISZINS = 1.27; // fiktiver Basiszinssatz der Dt. Bundesbank, Stand 01/2026
  const KATEGORIE = "Mahnungen";

  // Standard-Variablen, die eine Mahn-Vorlage mitbringt (überschreibbar je Durchlauf)
  const VAR_FRIST = { name: "frist_tage", type: "Zahl", default: "7", desc: "Zahlungsfrist in Tagen" };
  const VAR_GEBUEHR = { name: "mahngebuehr", type: "Zahl", default: "5,00", desc: "Mahngebühr in Euro" };
  const VAR_KONTO = { name: "kontonummer", type: "String", default: "DE21 6005 0101 0001 2345 67", desc: "Empfänger-IBAN" };

  const vorlagen = [
    {
      key: "erinnerung", tpl_id: "TPL-MAHN-004", label: "Zahlungserinnerung freundlich",
      kategorie: KATEGORIE, modified: "Vor 3 Wochen", stufe_nr: 0, ton: "freundlich",
      gebuehr: 0.00, zinsen: false,
      variablen: [VAR_FRIST],
      betreff: "Zahlungserinnerung — Objekt {objekt}",
      einleitung:
        "sicher ist es Ihrer Aufmerksamkeit entgangen: Für die unten genannten Beträge konnten wir bisher keinen Zahlungseingang feststellen. Wir bitten Sie, den offenen Betrag bis zum {frist} auszugleichen.",
      schluss:
        "Sollten Sie die Zahlung zwischenzeitlich veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos. Bei Fragen erreichen Sie uns unter den oben genannten Kontaktdaten.",
    },
    {
      key: "mahnung_1", tpl_id: "TPL-MAHN-001", label: "1. Mahnung",
      kategorie: KATEGORIE, modified: "Vor 2 Tagen", stufe_nr: 1, ton: "sachlich",
      gebuehr: 5.00, zinsen: true,
      variablen: [VAR_FRIST, VAR_GEBUEHR, VAR_KONTO],
      betreff: "1. Mahnung — Objekt {objekt}",
      einleitung:
        "trotz unserer Zahlungserinnerung ist der nachfolgend aufgeführte Betrag noch offen. Wir fordern Sie hiermit auf, den Gesamtbetrag bis spätestens {frist} auf das unten genannte Konto zu überweisen.",
      schluss:
        "Für diese Mahnung berechnen wir eine Mahngebühr. Wir bitten um zeitnahen Ausgleich, um weitere Kosten zu vermeiden.",
    },
    {
      key: "mahnung_2", tpl_id: "TPL-MAHN-002", label: "2. Mahnung",
      kategorie: KATEGORIE, modified: "Vor 2 Tagen", stufe_nr: 2, ton: "bestimmt",
      gebuehr: 10.00, zinsen: true,
      variablen: [VAR_FRIST, VAR_GEBUEHR, VAR_KONTO],
      betreff: "2. Mahnung — Objekt {objekt}",
      einleitung:
        "leider haben Sie auf unsere bisherigen Schreiben nicht reagiert. Der offene Betrag ist nach wie vor nicht ausgeglichen. Wir setzen Ihnen hiermit eine letzte Frist bis zum {frist}.",
      schluss:
        "Wir weisen darauf hin, dass wir bei fruchtlosem Fristablauf weitere Schritte einleiten und zusätzlich anfallende Kosten in Rechnung stellen müssen.",
    },
    {
      key: "letzte_mahnung", tpl_id: "TPL-MAHN-003", label: "3. Mahnung (letzte Mahnung)",
      kategorie: KATEGORIE, modified: "Vor 1 Woche", stufe_nr: 3, ton: "streng",
      gebuehr: 20.00, zinsen: true,
      variablen: [VAR_FRIST, VAR_GEBUEHR, VAR_KONTO],
      betreff: "Letzte Mahnung vor Übergabe an das Inkasso — Objekt {objekt}",
      einleitung:
        "trotz mehrfacher Aufforderung ist der unten genannte Betrag weiterhin offen. Wir fordern Sie letztmalig auf, den Gesamtbetrag bis zum {frist} zu begleichen.",
      schluss:
        "Nach Ablauf dieser Frist übergeben wir die Forderung ohne weitere Ankündigung einem Inkassobüro bzw. unserem Rechtsanwalt. Die hierdurch entstehenden Kosten gehen zu Ihren Lasten.",
    },
    {
      key: "heizkosten", tpl_id: "TPL-MAHN-005", label: "Mahnung Heizkosten-Vorauszahlung",
      kategorie: KATEGORIE, modified: "Vor 1 Monat", stufe_nr: 1, ton: "sachlich",
      gebuehr: 5.00, zinsen: true,
      variablen: [VAR_FRIST, VAR_GEBUEHR],
      betreff: "Rückständige Heizkosten-Vorauszahlung — Objekt {objekt}",
      einleitung:
        "für die unten aufgeführten Heizkosten-Vorauszahlungen konnten wir keinen Zahlungseingang feststellen. Wir bitten um Ausgleich bis zum {frist}, damit die Versorgung sichergestellt bleibt.",
      schluss:
        "Bei weiterhin ausbleibender Zahlung behalten wir uns vor, die Vorauszahlungen anzupassen und die offene Forderung beizutreiben.",
    },
    {
      key: "aussergerichtlich", tpl_id: "TPL-MAHN-006", label: "Außergerichtliche Mahnung",
      kategorie: KATEGORIE, modified: "Vor 2 Monaten", stufe_nr: 3, ton: "streng",
      gebuehr: 25.00, zinsen: true,
      variablen: [VAR_FRIST, VAR_GEBUEHR, VAR_KONTO],
      betreff: "Außergerichtliche Mahnung — Objekt {objekt}",
      einleitung:
        "wir setzen Ihnen hiermit eine letzte außergerichtliche Frist bis zum {frist}, um den vollständigen Betrag auszugleichen. Wir weisen ausdrücklich auf den bestehenden Zahlungsverzug hin.",
      schluss:
        "Nach fruchtlosem Fristablauf leiten wir ohne weitere Ankündigung das gerichtliche Mahnverfahren ein. Die hierdurch entstehenden Kosten tragen Sie.",
    },
    {
      key: "inkasso", tpl_id: "TPL-MAHN-007", label: "Inkasso-Ankündigung",
      kategorie: KATEGORIE, modified: "Vor 4 Monaten", stufe_nr: 3, ton: "streng",
      gebuehr: 30.00, zinsen: true,
      variablen: [VAR_FRIST, VAR_GEBUEHR, VAR_KONTO],
      betreff: "Ankündigung der Inkasso-Übergabe — Objekt {objekt}",
      einleitung:
        "trotz mehrfacher Mahnung ist die Forderung weiterhin offen. Wir kündigen hiermit an, die Forderung nach dem {frist} an ein Inkasso-Unternehmen zu übergeben.",
      schluss:
        "Sie können die Übergabe nur durch vollständige Zahlung bis zur genannten Frist abwenden. Die Kosten des Inkasso-Verfahrens gehen zu Ihren Lasten.",
    },
    {
      key: "ratenangebot", tpl_id: "TPL-MAHN-008", label: "Mahnung mit Ratenangebot",
      kategorie: KATEGORIE, modified: "Vor 5 Monaten", stufe_nr: 2, ton: "entgegenkommend",
      gebuehr: 10.00, zinsen: true,
      variablen: [VAR_FRIST, VAR_GEBUEHR, VAR_KONTO],
      betreff: "Mahnung mit Angebot einer Ratenzahlung — Objekt {objekt}",
      einleitung:
        "der unten genannte Betrag ist weiterhin offen. Sollte eine Zahlung in einer Summe nicht möglich sein, bieten wir Ihnen eine Ratenzahlung an. Bitte melden Sie sich bis zum {frist} bei uns.",
      schluss:
        "Bitte nehmen Sie zeitnah Kontakt mit uns auf, damit wir eine einvernehmliche Lösung finden und weitere Schritte vermeiden können.",
    },
  ];

  const vorlageByKey = Object.fromEntries(vorlagen.map((v) => [v.key, v]));

  // empfohlene nächste Vorlage je nach erreichter Mahnstufe
  const naechsteVorlageKey = (stufe) =>
    stufe >= 3 ? "letzte_mahnung" : stufe === 2 ? "letzte_mahnung" : stufe === 1 ? "mahnung_2" : stufe === 0 ? "mahnung_1" : "erinnerung";

  const zinssatzFuer = (typ) =>
    Math.round((BASISZINS + (typ === "gewerbe" ? 9 : 5)) * 100) / 100;

  window.MAHNUNG = {
    TODAY, absender, mieter, vorlagen, vorlageByKey,
    naechsteVorlageKey, zinssatzFuer, BASISZINS,
    overdueDays,
  };
})();
