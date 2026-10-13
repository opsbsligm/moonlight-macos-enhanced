//
//  USBMenuStatus.h
//  Moonlight
//
//  The one line the stream sidebar puts above the device list, decided from what this
//  process actually knows rather than from a string someone typed next to the menu.
//
//  The sidebar used to carry a fixed caption. It was true the day it was written -- an
//  ad-hoc build cannot load a driver extension, so no session could take a device -- and
//  it stayed true only by accident: the same five words also covered "the feature is off",
//  "we never asked this host", "this host says no", and "this host did not answer". Those
//  are four different places for a player to look, and a caption that cannot tell them
//  apart sends somebody to their PC's settings over a signature this repository has never
//  had. The settings pane already refuses that way -- DeviceRedirectionPanelModel answers
//  with the first precondition still missing -- and the sidebar is the surface where the
//  conflation actually costs something, because it is the one open during a stream.
//
//  Why this is a C header of inline decisions and not Objective-C, the same reason as
//  USBScanPolicy.h beside it: the answer is a total function of a handful of booleans and
//  one small enum, and a decision that compiles under plain `cc -std=c11` can be replayed
//  case by case with planted defects. A state machine that can only be exercised by opening
//  a menu is a state machine whose wrong branch nobody has ever watched.
//
//  What this file deliberately does not do: it never infers a host's answer. An unasked
//  question stays its own state and refuses for its own reason; a request that went out and
//  heard nothing is "unreachable", not "refused", because the host made no decision this
//  menu is entitled to report. Those two share a verdict and never share a sentence.
//

#pragma once
#include <stdbool.h>
#include <stdint.h>

/// Which precondition is the first thing standing between this device list and a handover.
/// The order is the whole content of this file, and it is the order of what a player can act
/// on: a build that cannot load a driver is a fact about this binary that no setting of theirs
/// can change, so it is answered before their own switches, and their own switches before a
/// question asked of somebody else's machine.
typedef enum {
    /// This binary's signature cannot host a driver extension, whatever else is true. Read
    /// from the running executable by CodeSignatureProfile, never asserted by the menu.
    MLUSBMenuCapabilityBuildCannotLoadDriver = 0,
    /// The player's own master switch. The one state here they can leave this menu to fix.
    MLUSBMenuCapabilityFeatureDisabled = 1,
    /// A question went out to the host and nothing answerable came back. A network fact, not
    /// the host's decision, and it must not be worded as one.
    MLUSBMenuCapabilityHostUnreachable = 2,
    /// Nothing has been asked of this host during this session -- including the case of a host
    /// this client is not paired with, where asking would be answered by the host's own door.
    /// Distinct from a refusal on purpose: "not asked" is this app's gap, "refused" is the
    /// host's answer.
    MLUSBMenuCapabilityHostNotAsked = 3,
    /// The host answered, and the answer was not an explicit yes.
    MLUSBMenuCapabilityHostRefused = 4,
    /// The host offered the exchange and then said it has nowhere to put a device. Offered and
    /// full are different sentences from refused: one is a retry later, the other is a feature
    /// that machine does not have.
    MLUSBMenuCapabilityHostOutOfSlots = 5,
    /// The host is reachable and heard the question, but answered with its own status of
    /// "somewhere else". The one state here that resolves by waiting rather than by changing
    /// anything, so it must not borrow either the network sentence or the refusal sentence.
    MLUSBMenuCapabilityHostBusy = 6,
    /// Every precondition this menu can observe holds. Not a claim that a device is connected,
    /// and not a claim that the steps behind this menu (bind, state, upload) would succeed --
    /// only that nothing in front of them is missing.
    MLUSBMenuCapabilityReady = 7,
} MLUSBMenuCapability;

/// The four shapes a host's answer arrives in, spelled the same way DeviceRedirectionPanelModel
/// spells them. Kept as plain ints here so this header stays free of the Objective-C layers; the
/// sidebar passes the value it already holds, and the numeric agreement is pinned by the gate.
enum {
    MLUSBMenuHostClaimNotAsked = 0,
    MLUSBMenuHostClaimRefused = 1,
    MLUSBMenuHostClaimOffered = 2,
    MLUSBMenuHostClaimUnreachable = 3,
    /// The transport worked and the document parsed, but the host answered its own status as
    /// not-OK. On Sunshine-shaped hosts that is what a machine mid-session says to a capability
    /// question: it is reachable, it heard the question, and it is not answering right now.
    /// Folding that into `Unreachable` would send a player to their router over their own PC
    /// being busy, which is the same class of misdirection this file exists to remove. The four
    /// states above keep the panel's numbers exactly; Busy is the menu's own fifth.
    MLUSBMenuHostClaimBusy = 4
};

/// Free virtual-USB slots the host reported, or this sentinel when it has not said. Not zero:
/// zero is a real answer meaning "offered, and full", and a caller that cannot tell the two
/// apart would either retry a full host forever or refuse a host that merely has not replied.
enum { MLUSBMenuSlotsUnknown = -1 };

/// The translation key for one capability state. One spelling per state, spelled here rather
/// than at the call sites, because a menu that invents its own key names is a menu where a
/// state can silently lose its sentence -- and the fallback for a missing key is the key
/// itself, which reads to a player like a bug report rather than a caption.
static inline const char *MLUSBMenuCapabilityKey(MLUSBMenuCapability capability) {
    switch (capability) {
        case MLUSBMenuCapabilityBuildCannotLoadDriver: return "USB blocked by this build";
        case MLUSBMenuCapabilityFeatureDisabled: return "USB permissions disabled here";
        case MLUSBMenuCapabilityHostUnreachable: return "USB host unreachable";
        case MLUSBMenuCapabilityHostNotAsked: return "USB host not asked";
        case MLUSBMenuCapabilityHostRefused: return "USB host refused";
        case MLUSBMenuCapabilityHostOutOfSlots: return "USB host has no free slots";
        case MLUSBMenuCapabilityHostBusy: return "USB host busy";
        case MLUSBMenuCapabilityReady: return "USB ready to connect devices";
    }
    return "USB host not asked";
}

/// The stable machine name for one capability state: the string the log gets, and the one a
/// screenshot's caption came from, so a support thread can match the two.
static inline const char *MLUSBMenuCapabilityName(MLUSBMenuCapability capability) {
    switch (capability) {
        case MLUSBMenuCapabilityBuildCannotLoadDriver: return "build-cannot-load-driver";
        case MLUSBMenuCapabilityFeatureDisabled: return "feature-disabled";
        case MLUSBMenuCapabilityHostUnreachable: return "host-unreachable";
        case MLUSBMenuCapabilityHostNotAsked: return "host-not-asked";
        case MLUSBMenuCapabilityHostRefused: return "host-refused";
        case MLUSBMenuCapabilityHostOutOfSlots: return "host-out-of-slots";
        case MLUSBMenuCapabilityHostBusy: return "host-busy";
        case MLUSBMenuCapabilityReady: return "ready";
    }
    return "host-not-asked";
}

/// Decide the sidebar's caption. `driver_can_load` comes from the running binary's signature,
/// `feature_enabled` from the player's switch, `host_paired` from this session's own host record,
/// `host_claim` from what the host answered when it was asked, and `free_slots` from what it said
/// about capacity.
///
/// An unpaired host never reaches a host-shaped verdict: nothing was asked of it, so this menu has
/// no answer to report and says so instead of borrowing somebody else's refusal.
static inline MLUSBMenuCapability MLUSBMenuCapabilityForInputs(
    bool driver_can_load, bool feature_enabled, bool host_paired,
    int host_claim, int free_slots) {
    if (!driver_can_load) return MLUSBMenuCapabilityBuildCannotLoadDriver;
    if (!feature_enabled) return MLUSBMenuCapabilityFeatureDisabled;
    if (!host_paired) return MLUSBMenuCapabilityHostNotAsked;
    if (host_claim == MLUSBMenuHostClaimBusy) return MLUSBMenuCapabilityHostBusy;
    if (host_claim == MLUSBMenuHostClaimUnreachable) return MLUSBMenuCapabilityHostUnreachable;
    if (host_claim == MLUSBMenuHostClaimNotAsked) return MLUSBMenuCapabilityHostNotAsked;
    if (host_claim != MLUSBMenuHostClaimOffered) return MLUSBMenuCapabilityHostRefused;
    if (free_slots == 0) return MLUSBMenuCapabilityHostOutOfSlots;
    return MLUSBMenuCapabilityReady;
}

/// Everything one `/serverinfo` exchange can leave behind, in the shape the sidebar can hold
/// without importing the network layer. Each field is something the caller observed and not
/// something it concluded, which is the only reason the verdict below can be replayed: a caller
/// that arrives with a conclusion already drawn has secretly written the decision twice.
typedef struct {
    /// The request went out and nothing answerable returned -- it failed, timed out, or the
    /// connection never opened. Separate from a document that arrived and said no.
    int transport_failed;
    /// A document carrying a status code came back. The one fact that separates "this machine
    /// answered" from "something on this address answered", and the reason a bare socket success
    /// is not an answer.
    int document_parsed;
    /// The status code the document reported for itself, or zero when there was no document.
    int status_code;
    /// The document named this session's host and no other. Several machines can answer one
    /// address space, and crediting a stranger's capability bit would hand devices to a host
    /// that never offered them.
    int answered_uuid;
    /// The document's own state ended with the server's busy suffix. This is the only place the
    /// word "busy" is allowed to come from: it is the host's reported state, not a client's guess
    /// from a refused connection.
    ///
    /// It is read only when the host's own status is not OK, and that restriction is deliberate. A
    /// host mid-session reports itself busy, and a host mid-session is exactly the host whose
    /// sidebar is open -- so letting that suffix outrank a capability the same document advertised
    /// would make every successful stream cost the player a "host busy" line, and would describe
    /// the one precondition USB redirection does not have.
    int state_says_busy;
    /// The capability tag this feature reads came back present and truthy. Absent is the host not
    /// having the feature, which is its own sentence and not a network one.
    int advertised;
} MLUSBMenuHostAnswer;

/// Turn one observed exchange into the claim the sidebar is allowed to make.
///
/// The order is a claim about evidence, not about convenience: something that was never heard may
/// not be reported as an answer, something that answered as somebody else may not be reported as
/// this host's answer, and only then does the host's own verdict get read. A client that read the
/// capability bit before checking who signed it would show a stranger's feature as this host's.
///
/// A host whose own status is not OK gets one more question asked of it before it is called a
/// refusal. "This machine is not answering right now" and "this machine declines" send a player to
/// two different places -- one waits, the other edits a setting -- and the document in hand is the
/// only place that difference can be read.
static inline int MLUSBMenuHostClaimFromAnswer(MLUSBMenuHostAnswer answer) {
    if (answer.transport_failed || !answer.document_parsed) {
        return MLUSBMenuHostClaimUnreachable;
    }
    if (!answer.answered_uuid) return MLUSBMenuHostClaimUnreachable;
    if (answer.status_code != 200) {
        return answer.state_says_busy ? MLUSBMenuHostClaimBusy : MLUSBMenuHostClaimRefused;
    }
    return answer.advertised ? MLUSBMenuHostClaimOffered : MLUSBMenuHostClaimRefused;
}
