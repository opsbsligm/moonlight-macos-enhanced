# Storing a Windows credential (issue #43): the design before the code

## 1. What is being asked, and what is not

Issue 43 asks the client to remember the Windows password and sign the host in by itself.
That is one feature and three questions people skip:

1. Where does a domain password live on a machine that is, from Windows' point of view, a
   client of questionable trust?
2. What happens when the host says no -- because a wrong password is not a retryable error
   on a domain account, it is a lockout timer?
3. Who can read it back, from the same user account, on a machine with no sandbox and an
   ad-hoc signature?

The SAS path already exists (a bindable `Ctrl+Alt+Del` preset), and the Keychain already
holds the pairing identity, so the injection and storage primitives are in the tree. What is
missing is the decision, and a feature that stores a domain password quietly is not one to
implement by accident. This file is that decision, written down before a line of code.

## 2. Where the secret may live, and where it may not

| Place | Verdict | Why |
| --- | --- | --- |
| macOS Keychain, one item per host | **allowed** | The item is the unit a user can inspect and delete, and it is the only store on this platform that hands out a secret with an accessibility class attached. |
| `UserDefaults` / the host settings record | **forbidden** | The settings record is copied, synced, exported and pasted. It is the format people attach to bug reports. |
| Any log line, including the debug log | **forbidden** | The curated log is written to a file, and the diagnostics report reads the tail of it. The report's redaction rules are a second line of defence, not a licence to write. |
| Process memory across the whole session | **discouraged** | Keep it for the sign-in attempt, not for the life of the stream. |
| Any file under the app's container or `Application Support` | **forbidden** | A plaintext file has no access control beyond the user's own permissions, which is every process running as that user. |

Key attributes, stated so a reviewer can check them rather than trust them:

- `kSecAttrService` = `std.skyhua.MoonlightMac2.windows-credential`, `kSecAttrAccount` = the
  host UUID. The service name carries the bundle identifier, not the product name, so the
  rename to `MoonlightEnhanced.app` does not orphan stored credentials.
- `kSecAttrAccessible` = `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. After first
  unlock, because signing in is a foreground action; ThisDeviceOnly, because a Time Machine
  restore to another Mac should not resurrect a domain password.
- No shared access group. This app is ad-hoc signed, so the group is whatever the signature
  gives it, which is to say: no second app should be able to ask for it.

## 3. The behaviour, not just the storage

1. **Opt-in per host, off by default, never inherited.** The toggle lives on the host, not in
   global settings, because the password belongs to a machine and an account on it.
2. **The UI says what it stores and where.** One sentence: the password goes into the macOS
   Keychain on this Mac and is never sent anywhere except to that host during sign-in.
3. **A visible forget control.** "Clear stored password" beside the toggle, and it clears the
   Keychain item rather than a flag that leaves the item behind.
4. **Attempt cap, stated as a number.** Two failed sign-ins per stream start, then stop and
   show the manual field. Domain accounts lock after a small number of failures, and a client
   that retries on "wrong password" is the reason helpdesks hate automation. A host that
   rejects the credential gets one retry per attempt, and never after that within the same
   session.
5. **Never auto-enable.** A failed sign-in must not flip the toggle on, must not "remember"
   the password the user typed to recover, and must not re-arm a toggle the user cleared.
6. **Say which step failed.** "Injected" and "accepted" are different facts: the client can
   prove it sent the SAS and the credential, and cannot see what Windows did with them. The
   status wording has to stop at what the client knows.

## 4. Non-goals

No Kerberos or NTLM ticket handling, no CredSSP, no domain join, no password change or
recovery, no storing anything obtained by watching what the user types into the host. The
feature is "type it once, and the client presses the keys for you", and every scope increase
beyond that needs this document rewritten rather than a flag added.

## 5. What would make this a gate, not a promise

- A harness that plants a password into the log body and into a host record and refuses the
  build if either reaches the diagnostics report -- the report already has a `password`
  redaction rule, so the new half is asserting the *storage* code never writes it.
- A constraint that the credential is read from the Keychain and from nowhere else: one
  function owns the read, and the tree refuses a second caller.
- A test for the accessibility class, because `AfterFirstUnlock` versus `WhenUnlocked` is the
  difference between "a locked Mac holds no password" and a claim about it.
- The attempt cap written as a constant the harness can plant a defect into, since "stops
  trying" is the property an implementation gets wrong under time pressure.

## 6. Open questions for the maintainer

1. Does upstream want auto-sign-in in a client distributed without a Developer ID and
   notarization? The answer decides whether this is a pull request or a documented refusal.
2. Should the credential be asked for at all when the host can be configured for autologon,
   which is the same convenience with the secret kept on the machine that owns it?
3. Is a build flag acceptable -- the feature compiled but off in released images until (1) is
   answered -- or does that just create a second code path nobody tests?

## 7. Recommendation

Do not implement it in this branch yet. Ship the design: the attempt cap and the accessibility
class are the parts that could hurt a user, and both are cheap to get wrong. If the maintainers
want the feature regardless, it lands behind a per-host opt-in with the six behaviours above,
with the four gates in section 5 arriving in the same pull request as the code, not after it.
