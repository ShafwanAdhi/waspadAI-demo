# WaspadAI --- Project Context

> **Purpose:** Product and UX context for AI agents working on the
> WaspadAI website.\
> **Scope:** Non-technical. This document defines what WaspadAI is, who
> it serves, what the experience should accomplish, and what must remain
> inside or outside the current website.

------------------------------------------------------------------------

## 1. Product Identity

**WaspadAI** is a digital awareness platform that helps people deal with
suspicious or questionable information before they make a decision.

The website focuses on the **Verification** experience. Users bring
information they are unsure about, WaspadAI examines it, explains the
result, and gives them a practical next step.

WaspadAI should feel like a **trusted verification companion**, not a
general-purpose chatbot.

### Core idea

> **Bring what makes you unsure. Understand what was found. Decide what
> to do next.**

------------------------------------------------------------------------

## 2. Website Scope

The current website contains three pages:

-   **Home** --- landing page that introduces WaspadAI and directs users
    toward verification;
-   **Chat** --- the main verification workspace;
-   **About** --- explains WaspadAI, its purpose, and how verification
    works.

The website represents the **Verification capability** of the broader
WaspadAI product.

The experience should remain focused on helping users check suspicious
information. Other product capabilities may exist in the broader
WaspadAI concept but should not be pulled into the website unless
explicitly requested.

------------------------------------------------------------------------

## 3. Home Page

Home is the landing page and the first point of contact for visitors.

Its primary job is to make the value of WaspadAI understandable within a
few seconds and guide the user toward verification.

The Home page should communicate:

-   what WaspadAI is;
-   what problem it helps with;
-   what kinds of information users can check;
-   what users receive after checking;
-   why the verification result can be trusted;
-   a clear path into the Chat verification experience.

### Main message

The page should communicate a simple idea:

> **Ragu dengan informasi yang kamu terima? Periksa sebelum bertindak.**

The exact copy can vary, but the meaning should remain consistent.

### Suggested Home structure

``` text
HERO
  ↓
What WaspadAI helps you check
  ↓
How verification works
  ↓
Why the result is trustworthy
  ↓
Example verification result
  ↓
Call to verify
```

The Home page should not become a long product brochure. Its role is to
establish context, build initial trust, and move the user toward the
core action.

------------------------------------------------------------------------

## 4. Full Product Context

The broader WaspadAI concept has three main areas:

-   **Verifikasi** --- help users examine questionable information;
-   **Pelajari** --- help users build digital awareness;
-   **Koneksi** --- allow users to share and discuss suspicious cases.

The current website focuses exclusively on **Verifikasi**.

In the full product, verification can be initiated from the user's
mobile context through a floating interaction and screen capture. Those
mechanisms belong to the broader product concept, but they are not part
of the current website experience.

The website replaces that interaction with direct input through the Chat
page.

------------------------------------------------------------------------

## 5. Primary User

The primary audience is people with varying levels of digital literacy,
with particular attention to **rural communities and users who may be
exposed to scams, misleading information, phishing, and social
engineering**.

The user may receive information through:

-   WhatsApp;
-   social media;
-   private messages;
-   community groups;
-   forwarded messages;
-   websites;
-   promotional offers;
-   messages claiming to represent an institution.

The user does not necessarily know how to independently verify the
information.

The important user characteristic is not lack of intelligence or
technical ability. The problem is that **digital information can look
convincing while its origin, claim, or requested action is difficult to
assess**.

------------------------------------------------------------------------

## 6. User Situation

A typical situation begins outside WaspadAI.

The user sees something that makes them hesitate:

> "Is this really from the bank?"

> "Is this government assistance information real?"

> "Should I click this link?"

> "Is this message a scam?"

> "Is this news actually true?"

The user then brings the information to WaspadAI.

This means the user's starting point is **uncertainty**, not curiosity
about AI.

The product should therefore immediately communicate:

**"Send it here. We will help you check it."**

------------------------------------------------------------------------

## 7. User Problem

The central problem is:

> Users may encounter information that looks credible but do not have a
> simple way to determine whether it is trustworthy, risky, or safe to
> act on.

A useful verification experience therefore needs to answer three
practical questions:

1.  **What is this information claiming?**
2.  **What evidence supports or contradicts it?**
3.  **What should I do now?**

------------------------------------------------------------------------

## 8. Core User Job

When the user encounters suspicious information, their job is simple:

**Check before acting.**

WaspadAI supports this by helping the user:

-   submit the information;
-   understand the claim;
-   see the verification result;
-   understand why the result was reached;
-   assess the potential risk;
-   decide on the next action.

------------------------------------------------------------------------

## 9. What the User Puts In

The user can provide information directly through the Chat page.

### Text

A copied message, claim, headline, or question.

Example:

> "Benarkah ada bantuan pemerintah sebesar Rp5 juta yang bisa dicairkan
> melalui link ini?"

### Link

A URL that appears in a suspicious message or webpage.

### Image

A screenshot or image containing information the user wants to check.

The user should experience all of these as one simple action:

> **Send the information you want to check.**

They should not need to understand how the underlying system processes
the content.

------------------------------------------------------------------------

## 10. What WaspadAI Gives Back

The result should help the user make a decision.

The most important information should appear in this order:

**Verdict → Risk → Reason → Evidence → Action**

### Verdict

The system communicates the current assessment of the information.

Possible outcomes can include:

-   **Valid**
-   **Hoaks**
-   **Menyesatkan**
-   **Waspada**
-   **Belum Terverifikasi**

The wording should remain understandable to the target user.

### Risk

Risk communicates how carefully the user should treat the information.

Examples:

-   Rendah
-   Sedang
-   Tinggi

For scam-like content, risk may be more important than factual
classification because an interaction can be dangerous even when some of
its information is technically true.

### Reason

The user should understand why the result was given.

The explanation should identify the important finding rather than
produce a long AI monologue.

### Evidence

The result should show where the conclusion came from.

Evidence can include relevant official sources, credible publications,
fact-checking references, or other supporting material.

### Action

The user should know what to do next.

Examples:

-   Jangan klik link.
-   Jangan berikan OTP.
-   Jangan kirim uang.
-   Periksa melalui website resmi.
-   Jangan bagikan data pribadi.
-   Konfirmasi kepada pihak yang bersangkutan.

------------------------------------------------------------------------

## 11. What the User Takes Away

After verification, the user should leave with four things:

### Understanding

They know what the information is actually claiming.

### Confidence

They understand how strong or weak the available evidence is.

### Risk Awareness

They know whether the information requires caution.

### Next Action

They know what they should do after seeing the result.

The intended outcome is:

> **Understand → Assess → Decide → Act safely**

------------------------------------------------------------------------

## 12. What the User Does Next

The user's next action depends on the result.

### If the information appears safe or supported

The user can continue while remaining aware of the evidence and context.

### If the information is misleading or false

The user should avoid spreading or acting on it and can check the
referenced official source.

### If the information appears risky

The user should stop the requested action, such as clicking a suspicious
link, sending money, installing an unknown application, or sharing
sensitive information.

### If the information cannot be verified

The user should not receive an artificially confident answer.

The appropriate guidance is to seek stronger evidence or confirm the
information through a trusted official source.

------------------------------------------------------------------------

## 13. Verification Is Not Just Fact-Checking

WaspadAI should not be framed as a machine that simply labels everything
**true** or **false**.

The important question is often:

> **"Is this safe to trust or act on?"**

For example, a real institution may genuinely exist, but a message
impersonating that institution can still be dangerous.

Likewise, a message can contain a true fact while using that fact to
manipulate the user into:

-   giving an OTP;
-   transferring money;
-   opening a suspicious link;
-   installing an application;
-   sharing personal information.

Therefore, WaspadAI considers both **information credibility and
practical risk**.

------------------------------------------------------------------------

## 14. Evidence Comes Before Confidence

WaspadAI should communicate confidence according to the available
evidence.

The product should avoid presenting a definitive answer when the
evidence is weak, contradictory, outdated, or unavailable.

When evidence is insufficient, the correct experience is:

> **"Belum dapat diverifikasi."**

rather than inventing a conclusion.

This principle is central to the identity of WaspadAI.

------------------------------------------------------------------------

## 15. Chat Experience

The Chat page is the heart of the website.

It should not look like an open-ended AI playground.

The interface should make the verification purpose obvious from the
first screen.

### Empty State

The user should immediately understand:

-   what WaspadAI does;
-   what they can send;
-   what they will receive.

Example direction:

> **Ada informasi yang bikin ragu?**\
> Kirim pesan, link, atau gambar. WaspadAI akan membantu memeriksa
> informasinya dan menjelaskan apa yang perlu diperhatikan.

Quick examples can help users start:

-   Periksa pesan ini
-   Cek link ini
-   Apakah informasi ini benar?
-   Apakah ini penipuan?

------------------------------------------------------------------------

## 16. Conversation Behavior

The conversation should follow the user's verification task.

A typical exchange:

``` text
USER
"Apakah pesan ini benar?"

        ↓

WASPADAI
Memahami informasi yang dikirim

        ↓

WASPADAI
Memeriksa sumber dan bukti yang relevan

        ↓

WASPADAI
Menampilkan hasil

        ↓

USER
Memahami hasil dan menentukan tindakan
```

The assistant should not unnecessarily turn a verification request into
a long conversation.

If the input is sufficient, verify it.

If an important piece of information is missing, ask only for what is
necessary.

------------------------------------------------------------------------

## 17. Result Experience

The verification result should be visually distinct from ordinary chat
messages.

The user should be able to scan the result quickly.

Recommended hierarchy:

``` text
RESULT
↓
WHAT WAS CHECKED
↓
RISK
↓
WHY
↓
EVIDENCE
↓
WHAT TO DO
```

A user should understand the overall result without reading every
detail.

Additional evidence can be expandable so the interface remains readable.

The result can be shown in two modes:

-   **Poin-poin** for quick scanning, comparison, and source checking.
-   **Naratif** for users who prefer a short natural-language explanation.

Both modes must represent the same verification result. Switching mode
should not run a new check, change the verdict, or hide important safety
warnings and evidence.

------------------------------------------------------------------------

## 18. About Page

The About page explains WaspadAI without becoming a technical
documentation page.

It should answer:

### What is WaspadAI?

A tool that helps users check questionable information and make safer
digital decisions.

### Why does it exist?

Because misleading information and scams can appear convincing,
especially when users receive them through familiar channels.

### How does it work?

``` text
Send information
      ↓
WaspadAI checks it
      ↓
Evidence is examined
      ↓
Result is explained
      ↓
User decides what to do
```

### What makes it different?

The focus is on **evidence, explanation, risk, and action**, rather than
simply generating an AI answer.

------------------------------------------------------------------------

## 19. Product Personality

WaspadAI should feel:

-   approachable;
-   clear;
-   credible;
-   calm;
-   modern;
-   practical;
-   friendly without becoming childish.

The product should feel appropriate for younger users while remaining
trustworthy for adults.

It should not feel:

-   corporate-heavy;
-   bureaucratic;
-   overly academic;
-   intimidating;
-   like a generic AI dashboard;
-   like a generic ChatGPT clone.

------------------------------------------------------------------------

## 20. Visual Direction

The visual language should support trust without becoming visually
sterile.

The existing WaspadAI direction uses a **yellow and blue** combination
as a recognizable visual identity.

Use color with purpose:

-   yellow can emphasize attention, activity, and WaspadAI identity;
-   blue can support trust, information, and interface structure;
-   status colors should remain clear when communicating verification or
    risk.

Avoid making the entire interface a single-color composition.

The design should have hierarchy through:

-   spacing;
-   typography;
-   card structure;
-   contrast;
-   selective color;
-   clear grouping.

Illustrations or clay-style 3D characters can be used when they add
context, especially in explanatory areas. They should support the
content rather than become decoration without purpose.

------------------------------------------------------------------------

## 21. Content Principles

WaspadAI speaks in **plain Indonesian**.

Use:

-   short sentences;
-   familiar words;
-   direct explanations;
-   practical instructions;
-   specific findings.

Avoid:

-   unnecessary technical terminology;
-   long introductory statements;
-   exaggerated AI language;
-   generic motivational copy;
-   overly formal bureaucratic wording;
-   vague statements;
-   excessive explanation when one sentence is enough.

### Preferred

> **Link ini berisiko.**\
> Domainnya tidak sesuai dengan website resmi yang digunakan bank
> tersebut.

### Avoid

> **Berdasarkan analisis komprehensif berbasis kecerdasan buatan, dapat
> disimpulkan bahwa terdapat indikasi potensi risiko yang perlu
> diperhatikan lebih lanjut.**

The first version helps the user decide. The second sounds like generic
AI output.

------------------------------------------------------------------------

## 22. Trust Principles

Trust is built through the behavior of the product.

WaspadAI should:

-   show the basis for important conclusions;
-   distinguish evidence from interpretation;
-   acknowledge uncertainty;
-   avoid fabricated sources;
-   avoid pretending certainty;
-   provide practical safety advice;
-   keep explanations understandable.

The user should be able to ask:

> **"Kenapa hasilnya begitu?"**

and find the answer directly in the result.

------------------------------------------------------------------------

## 23. Safety Principles

The verification experience should prioritize preventing harmful user
actions.

When the content involves potential:

-   phishing;
-   financial scams;
-   impersonation;
-   malicious downloads;
-   credential theft;
-   suspicious payment requests;
-   sensitive personal information;

the interface should make the relevant risk and recommended action
prominent.

Do not encourage the user to test a suspicious link or interact with a
suspected scam merely to obtain more information.

------------------------------------------------------------------------

## 24. Important Product Distinctions

### Verification vs Chat

Chat is the interface.

**Verification is the product capability.**

### Verdict vs Explanation

A verdict tells the user the result.

An explanation tells them why.

Both are required.

### Evidence vs AI Opinion

Evidence should be presented as the basis for the verification.

AI-generated interpretation should not be presented as independent
proof.

### Risk vs Truth

A piece of information can be true while the requested action is unsafe.

The product must be able to communicate that distinction.

------------------------------------------------------------------------

## 25. Website Success Criteria

The website succeeds when a first-time user can quickly understand:

**What is this?**

> A place to check information that feels suspicious.

**What do I send?**

> A message, link, text, or image.

**What do I get?**

> A result, explanation, evidence, and recommended action.

**What do I do afterward?**

> Make a safer decision based on what was found.

The Home page should establish this value quickly, while the Chat page
should make the actual verification process straightforward.

------------------------------------------------------------------------

## 26. Explicit Out-of-Scope Items

Do not introduce these into the current website unless explicitly
requested:

-   floating button;
-   MediaProjection;
-   Android-specific interaction;
-   background screen monitoring;
-   automatic verification while using another application;
-   WhatsApp integration;
-   full Pelajari feature;
-   full Koneksi feature;
-   community moderation dashboard;
-   admin dashboard;
-   Family Guard;
-   Recovery/SOS;
-   user management;
-   complex account management;
-   general-purpose AI assistant features.

These may exist in the broader WaspadAI product concept but are not part
of the current website.

------------------------------------------------------------------------

## 27. Agent Guardrails

When making product, UX, content, or UI decisions for this project:

1.  Keep the **Verification** use case at the center.
2.  Treat **Chat** as the interface, not the product itself.
3.  Keep the website scope to **Home, Chat, and About**.
4.  Design for users who may have limited confidence in evaluating
    digital information.
5.  Prioritize **verdict, risk, reason, evidence, and action**.
6.  Never fabricate evidence, sources, or certainty.
7.  Prefer clear Indonesian over technical language.
8.  Do not add features merely because they are common in AI products.
9.  Do not turn the interface into a generic AI chatbot.
10. Keep the experience practical: **check → understand → decide**.
11. When uncertain, preserve uncertainty rather than inventing an
    answer.
12. Remember that the full WaspadAI product is larger than the current
    website.
13. Use Home to establish context and trust, Chat to perform
    verification, and About to explain the product.

------------------------------------------------------------------------

## 28. Decision Priority

If a future design decision conflicts with this document, use the
following priority:

``` text
USER SAFETY
    ↓
VERIFICATION PURPOSE
    ↓
CLARITY OF RESULT
    ↓
EVIDENCE & TRUST
    ↓
USER NEXT ACTION
    ↓
VISUAL / INTERACTION DETAIL
```

A visually attractive feature that makes verification less clear should
be rejected.

A sophisticated feature that does not improve the user's ability to
understand or act safely should remain outside the current website.

------------------------------------------------------------------------

## 29. One-Line Product Definition

> **WaspadAI helps people check suspicious information, understand the
> evidence behind the result, and decide what to do next.**
