// mahn-letter.jsx — Live-A4-Briefvorschau des Mahnschreibens.

function LetterPreviewMH({ d }) {
  const A = window.MAHNUNG.absender;
  const ctx = {
    mieter: d.mieter.name,
    objekt: d.mieter.objekt,
    betrag: fmtEUR_mh(d.summe),
    frist: fmtDateLong_mh(d.frist),
    stufe: d.vorlageLabel,
    zweck: d.verwendungszweck,
    sachbearbeiter: A.sachbearbeiter,
    firma: A.firma,
  };
  const betreff = fillPlaceholders_mh(d.betreff, ctx);
  const einleitung = fillPlaceholders_mh(d.einleitung, ctx);
  const schluss = fillPlaceholders_mh(d.schluss, ctx);

  return (
    <div className="mh-letter" data-screen-label="Briefvorschau">
      <div className="mh-letter-page">
        {/* Briefkopf */}
        <div className="mh-letter-head">
          <div className="mh-letter-logo">
            <span className="mh-letter-logo-mark">HV</span>
            <div className="mh-letter-logo-text">
              <strong>{A.firma}</strong>
              <span>Immobilien · Hausverwaltung · Stuttgart</span>
            </div>
          </div>
          <div className="mh-letter-head-contact">
            <div>{A.strasse}</div>
            <div>{A.plz_ort}</div>
            <div>Tel. {A.telefon}</div>
            <div>{A.email}</div>
          </div>
        </div>

        {/* Absender-Zeile + Anschriftfeld */}
        <div className="mh-letter-sender-line">
          {A.firma} · {A.strasse} · {A.plz_ort}
        </div>
        <div className="mh-letter-addr-row">
          <div className="mh-letter-addr">
            {d.mieter.adresse.map((l, i) => (
              <div key={i} className={i === 0 ? "is-name" : ""}>{l}</div>
            ))}
          </div>
          <div className="mh-letter-meta">
            <div><span>Kundennr.</span>{d.mieter.id}</div>
            <div><span>Objekt</span>{d.mieter.einheit}</div>
            <div><span>Bearbeitung</span>{A.sachbearbeiter}</div>
            <div><span>Datum</span>{fmtDate_mh(d.mahndatum)}</div>
          </div>
        </div>

        {/* Betreff */}
        <div className="mh-letter-subject">{betreff}</div>

        {/* Anrede + Einleitung */}
        <p className="mh-letter-salut">{d.anrede}</p>
        {einleitung
          ? <p className="mh-letter-body">{einleitung}</p>
          : <p className="mh-letter-body is-empty">[ Einleitungstext — im Editor erfassen ]</p>}

        {/* Forderungstabelle */}
        <table className="mh-letter-table">
          <thead>
            <tr>
              <th>Beleg</th>
              <th>Datum</th>
              <th>Fällig</th>
              <th className="num">Tage</th>
              <th className="num">Betrag</th>
            </tr>
          </thead>
          <tbody>
            {d.posten.length === 0 && (
              <tr><td colSpan={5} className="mh-letter-table-empty">Keine Posten ausgewählt</td></tr>
            )}
            {d.posten.map((p) => (
              <tr key={p.beleg}>
                <td className="mono">{p.beleg}</td>
                <td>{fmtDate_mh(p.posting)}</td>
                <td>{fmtDate_mh(p.faellig)}</td>
                <td className="num">{p.overdue_days}</td>
                <td className="num">{fmtEUR_mh(p.offen)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={4}>Summe offene Hauptforderung</td>
              <td className="num">{fmtEUR_mh(d.hauptforderung)}</td>
            </tr>
            {d.zinsenAktiv && d.zinsBetrag > 0 && (
              <tr>
                <td colSpan={4}>Verzugszinsen ({fmtNum_mh(d.zinssatz)} % p.&nbsp;a.)</td>
                <td className="num">{fmtEUR_mh(d.zinsBetrag)}</td>
              </tr>
            )}
            {d.gebuehr > 0 && (
              <tr>
                <td colSpan={4}>Mahngebühr</td>
                <td className="num">{fmtEUR_mh(d.gebuehr)}</td>
              </tr>
            )}
            <tr className="is-grand">
              <td colSpan={4}>Zahlbetrag bis {fmtDate_mh(d.frist)}</td>
              <td className="num">{fmtEUR_mh(d.summe)}</td>
            </tr>
          </tfoot>
        </table>

        {/* Schlusstext */}
        {schluss
          ? <p className="mh-letter-body">{schluss}</p>
          : <p className="mh-letter-body is-empty">[ Schlusstext — im Editor erfassen ]</p>}

        <p className="mh-letter-body">
          Bitte überweisen Sie den Betrag unter Angabe des Verwendungszwecks
          <strong> {d.verwendungszweck}</strong> auf folgendes Konto:
        </p>
        <div className="mh-letter-bank">
          <div><span>Kontoinhaber</span>{A.firma}</div>
          <div><span>IBAN</span>{d.kontonummer || A.iban}</div>
          <div><span>BIC</span>{A.bic}</div>
          <div><span>Bank</span>{A.bank}</div>
        </div>

        {/* Grußformel */}
        <p className="mh-letter-greeting">Mit freundlichen Grüßen</p>
        <div className="mh-letter-sign">
          <div className="mh-letter-sign-line" />
          <div>{A.sachbearbeiter}</div>
          <div className="mh-letter-sign-sub">{A.firma}</div>
        </div>

        {/* Fußzeile */}
        <div className="mh-letter-foot">
          <div>
            <strong>{A.firma}</strong><br />
            {A.strasse} · {A.plz_ort}<br />
            Tel. {A.telefon} · {A.email}
          </div>
          <div>
            Geschäftsführer: {A.geschaeftsfuehrer}<br />
            USt-IdNr.: {A.ust}
          </div>
          <div>
            {A.bank}<br />
            IBAN {A.iban}<br />
            BIC {A.bic}
          </div>
        </div>
      </div>

      {/* Versand-Vermerk unter dem Blatt */}
      <div className="mh-letter-dispatch">
        Versand: <strong>{d.kanal}</strong>
        {d.kanal !== "Brief" && <span> · an {d.mieter.email}</span>}
        {" · "}1 Seite · PDF wird erzeugt
      </div>
    </div>
  );
}

Object.assign(window, { LetterPreviewMH });
