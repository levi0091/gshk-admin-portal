import { Link } from 'react-router-dom'

/**
 * Who puts the overall signature on an e-Signed ND2A (Levi 2026-11-13).
 *
 * Two tiles, in the family of the Route chooser (`meth-opt`): GSHK's e-Service
 * account, or a director's own e-Registry account. On an ND2A that changes
 * the company secretary GSHK is not yet related to the company, so the server
 * defaults to a director there — but only when one has an account to sign with.
 *
 * Each tile ends in a plate naming the CR account that will actually sign, so
 * the operator sees the credential before pressing anything. A director with no
 * complete e-Registry account is still listed (the board is never shown short),
 * disabled, with a link to the profile where the account is set up.
 *
 * The server decides everything that matters (`data.signer`): who may sign,
 * the default, and the stored choice. This component only draws it and sends
 * `{signing_party, signing_director_person_id}` through `onChoose`.
 */
/** True when the chosen signer cannot sign, so Validate must wait. */
export function signerBlocked(signer) {
  return Boolean(signer?.offered && signer.party === 'director' && !signer.director_ready)
}

/** The hint beside a held Validate button. */
export function signerBlockedHint(signer) {
  return signer?.gshk?.available === false
    ? 'Choose a director who can sign first, or file by the Manual route.'
    : 'Choose a director who can sign, or GSHK e-Service, first.'
}

/**
 * Who signs, READ-ONLY, for the Signing stage (Levi 2026-11-13: "only make them
 * select it once"). The choice is made on Data Verification, before CR
 * validates, because the signatory is inside the form CR checks. Signing only
 * restates it — the signer, the capacity and the CR account — and offers the
 * way back to change it. One stored value drives both screens, so they cannot
 * disagree.
 */
export function SignerSummary({ signer, signatory, canChange, onChange }) {
  if (!signer?.offered) return null
  const directorSigns = signer.party === 'director'
  const director = directorSigns
    ? (signer.candidates || []).find(c => c.person_id === signer.director_person_id) : null
  const blocked = signerBlocked(signer)
  const who = directorSigns ? director?.name : (signer.gshk?.signs_for || signatory?.name)
  const capacity = directorSigns ? 'Director'
    : (signatory?.selected_capacity || signatory?.default_capacity || signer.gshk?.capacity)
  const account = directorSigns ? director?.eservice_user_id : signer.gshk?.eservice_user_id
  // GSHK signs with the logged-in user's own e-Service account; without one CR
  // has nothing to sign with, so say so here rather than at CR.
  const noStaffAccount = !directorSigns && !signer.gshk?.eservice_user_id
  const back = canChange ? ' Choose who signs on Data Verification.' : ''

  return (
    <section className="oc-ss" data-testid="signer-summary" data-party={signer.party}
             aria-label="Who signs the form">
      <div className="oc-ss-main">
        <span className="oc-ss-k">Who signs the form</span>
        {who ? (
          <span className="oc-ss-who">
            <b>{who}</b>{capacity ? ` as ${capacity}` : ''}
            {director?.ceasing && <span className="oc-sc-leaving">resigning on this form</span>}
          </span>
        ) : (
          <span className="oc-ss-who">No director chosen</span>
        )}
        <span className="oc-ss-acct">
          {directorSigns ? "Director's e-Registry" : 'GSHK e-Service'}
          {account && !blocked && <span className="oc-sc-plate-v">{account}</span>}
        </span>
      </div>
      {canChange && (
        <button type="button" className="btn btn-sm btn-outline" onClick={onChange}>
          Change on Data Verification
        </button>
      )}
      {blocked && (
        <div className="oc-sc-warn" role="alert">
          {director ? `${director.name} cannot sign yet: ${director.reason || 'e-Registry not set up'}.`
            : 'No director who can sign is chosen.'}
          {back}
        </div>
      )}
      {noStaffAccount && (
        <div className="oc-sc-warn" role="alert">
          Your e-Service account is not set up. <Link to="/cr-credentials">Add it in CR Credentials</Link>
        </div>
      )}
      {directorSigns && director?.ready && director.id_mismatch && (
        <div className="oc-sc-warn" role="status">{director.id_mismatch}</div>
      )}
    </section>
  )
}

export default function SignerChoice({ signer, can, busy, validated, locked, onChoose }) {
  if (!signer?.offered) return null
  const candidates = signer.candidates || []
  const ready = candidates.filter(c => c.ready)
  const party = signer.party
  const directorSigns = party === 'director'
  const editable = can.write && !locked
  const anyReady = ready.length > 0
  const suggestDirector = signer.default === 'director'
  // GSHK cannot sign for a secretary this form only appoints: CR answers "The
  // user has no association with this company" (DEV 2026-11-13).
  const gshkOff = signer.gshk?.available === false

  function choose(body) {
    if (!editable || busy) return
    onChoose(body)
  }

  return (
    <fieldset className="oc-sc" data-testid="signer-choice" disabled={!editable || busy}>
      <legend className="oc-sc-legend">Who signs the form</legend>
      {gshkOff ? (
        <p className="oc-sc-why">
          {signer.gshk?.signs_for || 'The new secretary'} is not yet the company secretary, so
          CR will not accept its signature on this form. A director signs with their own
          e-Registry account; GSHK's TPSI account still validates, pays for and files it.
        </p>
      ) : signer.changes_secretary && (
        <p className="oc-sc-why">
          This form changes the company secretary, so a director is suggested to sign with
          their own e-Registry account. GSHK's TPSI account still files it.
        </p>
      )}

      <div className="oc-sc-options">
        <div className={`oc-sc-tile ${!directorSigns ? 'sel' : ''} ${gshkOff ? 'is-off' : ''}`}
             data-party="gshk">
          <label className="oc-sc-head">
            <input type="radio" name="oc-signer-party" className="oc-sc-radio"
                   checked={!directorSigns} disabled={gshkOff}
                   onChange={() => choose({ signing_party: 'gshk' })} />
            <span className="oc-sc-title">GSHK e-Service</span>
          </label>
          <p className="oc-sc-sub">
            Your own e-Service account from CR Credentials, signing for{' '}
            {signer.gshk?.signs_for || 'the company secretary'}
            {signer.gshk?.capacity ? ` as ${signer.gshk.capacity}` : ''}.
          </p>
          <div className="oc-sc-plate"
               data-state={gshkOff || !signer.gshk?.eservice_user_id ? 'missing' : 'ready'}>
            {gshkOff ? (
              <span>Not available: CR answers "The user has no association with this company"
                until it registers the new secretary.</span>
            ) : signer.gshk?.eservice_user_id ? (
              <><span className="oc-sc-plate-k">Signs with</span>
                <span className="oc-sc-plate-v">{signer.gshk.eservice_user_id}</span></>
            ) : (
              <span>Your e-Service account is not set up. <Link to="/cr-credentials">Add it in CR Credentials</Link></span>
            )}
          </div>
        </div>

        <div className={`oc-sc-tile ${directorSigns ? 'sel' : ''} ${anyReady ? '' : 'is-off'}`}
             data-party="director">
          <label className="oc-sc-head">
            <input type="radio" name="oc-signer-party" className="oc-sc-radio"
                   checked={directorSigns} disabled={!anyReady}
                   onChange={() => choose({ signing_party: 'director' })} />
            <span className="oc-sc-title">Director's e-Registry</span>
            {suggestDirector && <span className="oc-sc-tag">Suggested</span>}
          </label>
          <p className="oc-sc-sub">
            {anyReady
              ? 'A director signs as Director with the e-Registry account on their profile. A director resigning on this form may sign too.'
              : 'Director e-Registry is not set up. No director has an e-Registry account on their profile.'}
          </p>
          {candidates.length > 0 ? (
            <ul className="oc-sc-directors" aria-label="Directors who can sign">
              {candidates.map(c => {
                const picked = directorSigns && signer.director_person_id === c.person_id
                return (
                  <li key={c.person_id} className={`oc-sc-dir ${picked ? 'sel' : ''}`}
                      data-ready={c.ready ? 'yes' : 'no'}>
                    <label className="oc-sc-dir-row">
                      <input type="radio" name="oc-signer-director" className="oc-sc-radio sm"
                             checked={picked} disabled={!c.ready}
                             aria-label={`${c.name} signs`}
                             onChange={() => choose({ signing_party: 'director',
                               signing_director_person_id: c.person_id })} />
                      <span className="oc-sc-dir-name">
                        {c.name}
                        {c.ceasing && <span className="oc-sc-leaving">resigning on this form</span>}
                      </span>
                      {c.ready
                        ? <span className="oc-sc-plate-v">{c.eservice_user_id}</span>
                        : <span className="oc-sc-missing">{c.reason || 'e-Registry not set up'}</span>}
                    </label>
                    {!c.ready && c.profile_path && (
                      <Link className="oc-sc-setup" to={c.profile_path}>Set up on profile</Link>
                    )}
                    {c.ready && c.id_mismatch && picked && (
                      <div className="oc-sc-warn" role="status">{c.id_mismatch}</div>
                    )}
                  </li>
                )
              })}
            </ul>
          ) : (
            <div className="oc-sc-plate" data-state="missing">
              The company has no current natural-person director on record.
            </div>
          )}
          {directorSigns && !signer.director_ready && (
            <div className="oc-sc-warn" role="alert">
              {anyReady
                ? `No director chosen can sign yet. Choose one with e-Registry set up${gshkOff ? '' : ', or GSHK e-Service'}.`
                : `Set up a director's e-Registry on their profile${gshkOff ? ', or file by the Manual route' : ', or choose GSHK e-Service'}.`}
            </div>
          )}
        </div>
      </div>

      {locked ? (
        <p className="oc-sc-foot">The form is signed. Restart verification to change who signs.</p>
      ) : validated && editable ? (
        <p className="oc-sc-foot">Changing who signs sends the form back to CR to validate again.</p>
      ) : null}
    </fieldset>
  )
}
