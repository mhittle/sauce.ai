# G3: Community answer queue (10 threads)

**Status of every item: draft-not-posted.** Nothing has been posted, and no forum accounts were created or used.
Prepared 2026-11-26. I opened every thread listed (Discourse JSON or page fetch) on 2026-11-26. Each one returned HTTP 200 and was not marked closed or archived at the time.
Vendor quotes were checked on the vendor's own page on **2026-11-26**, unless another date is given.
Rules for each answer: it answers fully first, cites the vendor's own words with the date checked, has at most ONE link, and includes a disclosure line. HIPAA content is general information, not legal advice.

> Coverage note: Reddit (r/nocode, r/healthIT, r/medicine, r/lovable, r/replit, r/Bubbleio) and Quora could not be opened from this environment. reddit.com and old.reddit.com refused the fetch tool, Quora returned 403, and Reddit's JSON returned 403. The Base44 feedback board (feedback.base44.com) renders posts with JavaScript only, so the post text could not be read. No Lovable community thread could be opened. Per the brief, only threads I actually opened are listed.

---

## 1. Replit forum: "Is Replit Agent and Replit as a whole HIPAA compliant?"
- **URL:** https://replit.discourse.group/t/is-replit-agent-and-replit-as-a-whole-hipaa-compliant/4255
- **Date:** opened 2025-04-09; last reply 2025-06-11. Asked by a clinician who builds apps for their own practice.
- **Question (short quote):** "one roadblock in scaling this for my whole patient census has been HIPAA compatibility… I'm not sure if a BAA would be available from Replit"
- **Status:** draft-not-posted

**Draft answer:**
> Short version: on Replit's standard hosting there's no BAA, so real patient data shouldn't go into Replit-hosted apps or into the Agent chat.
>
> Replit says this itself. Its therapy-website-builder FAQ says: "Replit does not sign BAAs for its standard hosting services, so it is not a HIPAA-compliant builder out of the box," and "You cannot use Replit's standard deployment for websites that handle PHI." Its shared-responsibility doc lists "Regulatory compliance of your application… (for example, GDPR, CCPA, PHI, PCI DSS, HIPAA, SOC 2)" as the customer's job. (Both checked on Replit's own pages, 2026-11-26.) SOC 2 is a security attestation. It isn't a BAA.
>
> The pattern that works for clinicians: build and test in Replit with invented patients only, then deploy the exported code to hosting that signs a BAA with your practice. Each piece that touches PHI (database, auth, email/SMS, any LLM API) needs its own BAA. Add the app to your practice's security risk analysis before real patients use it, and run the plan past your privacy officer.
>
> Layer-by-layer notes with the dated Replit quotes: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/is-replit-hipaa-compliant/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes that page.

---

## 2. Replit forum: "HIPAA Compliance and BAA"
- **URL:** https://replit.discourse.group/t/hipaa-compliance-and-baa/10497
- **Date:** 2026-03-25 (last reply 2026-03-26)
- **Question (short quote):** "1 will Replit sign a HIPAA BAA and 2. is there an easier way to deploy applications to Azure."
- **Status:** draft-not-posted

**Draft answer:**
> 1) For standard hosting, no. Replit's own FAQ (therapy-website-builder page, checked 2026-11-26) says "Replit does not sign BAAs for its standard hosting services" and "You cannot use Replit's standard deployment for websites that handle PHI." I couldn't find anything in Replit's public docs about whether Enterprise or Bring Your Own Cloud changes that. If you need it, ask Replit sales in writing.
>
> 2) Your current setup is the right one: de-identified or synthetic data in Replit, production in your own Azure environment, covered by whatever BAA your organization already has with Microsoft (confirm that with your compliance team). To make the hand-off easier, push from Replit to GitHub and let a CI pipeline (GitHub Actions → Azure App Service or Container Apps) do the deploy. Your DevOps team then reviews the pipeline once, not every release. Keep the Azure credentials as pipeline secrets, not in the Replit workspace. Also make sure nothing in the Agent chat or the Replit database ever holds real PHI. The Agent context is part of the stack too.
>
> If useful, this lists each layer and which ones need a BAA: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/stack-checker/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes this checker.

---

## 3. Replit forum: "InsightScanAI – A medical analysis tool built on Replit" (reply asking about HIPAA)
- **URL:** https://replit.discourse.group/t/insightscanai-a-medical-analysis-tool-built-on-replit/4728
- **Date:** thread 2025-05-27; HIPAA question posted 2025-05-31
- **Question (short quote):** "Thank you for sharing. Is it HIPAA complaint ?"
- **Status:** draft-not-posted

**Draft answer:**
> Two questions are mixed together here. (a) Does HIPAA apply? It applies to covered entities (providers, plans, clearinghouses) and their business associates. A consumer tool that patients use on their own often isn't covered, but the moment a clinic uses it on its patients' images, it usually is. (b) If it applies, every vendor that receives the data needs a BAA. That includes the host and each AI API the images pass through.
>
> On the hosting layer, Replit says plainly (therapy-website-builder FAQ, checked 2026-11-26): "Replit does not sign BAAs for its standard hosting services." So for clinic use, the app would need to be deployed elsewhere, and each AI provider would need to be on a plan where that provider signs a BAA. Asking users to strip identifiers helps, but medical images often carry identifiers in metadata or burned into pixels, so I wouldn't rely on that alone.
>
> Dated Replit notes: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/is-replit-hipaa-compliant/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes that page.

---

## 4. Bubble forum: "HIPAA compliance!"
- **URL:** https://forum.bubble.io/t/hipaa-compliance/377467
- **Date:** 2025-08-01 (last reply 2026-01-27)
- **Question (short quote):** "There has to be a way that you could get HIPAA compliance for Bubble… I want to build my HIPAA dream app on Bubble!"
- **Status:** draft-not-posted

**Draft answer:**
> There's now an official path. Bubble's Support Center article "Is Bubble HIPAA compliant?" (dated October 21, 2026; checked 2026-11-26) says: "HIPAA and BAA support is available as an add-on to Bubble's Dedicated Enterprise plan. With it, Bubble signs a BAA with you and runs your app on dedicated, HIPAA-ready infrastructure." It adds: "any third-party service that receives PHI from your app needs its own signed BAA with you."
>
> So: on any other Bubble plan, keep to invented patient data. On Dedicated Enterprise with the add-on, you still have to set privacy rules correctly and get a BAA from every plugin or API that sees PHI. Jotform, Zoho and the rest each need their own BAA too. One caution: the older Bubble manual page on HIPAA still says Bubble "cannot support HIPAA compliant apps." The Support Center article is the newer one, so confirm the current terms with Bubble sales in writing.
>
> Dated summary of Bubble's pages: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/is-bubble-hipaa-compliant/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes that page.

---

## 5. Bubble forum: "Balancing Compliance & No-Code: Our New HIPAA-Ready Stack"
- **URL:** https://forum.bubble.io/t/balancing-compliance-no-code-our-new-hipaa-ready-stack/346026
- **Date:** thread 2024-10-28; the relevant discussion is Jan 18–20, 2026
- **Question (short quote):** "at least they could make it HIPAA compliant on the dedicated plans first." (2026-01-19)
- **Status:** draft-not-posted

**Draft answer:**
> Update for anyone finding this thread: that's roughly what happened. Bubble's Support Center (article dated October 21, 2026; checked 2026-11-26) says "HIPAA and BAA support is available as an add-on to Bubble's Dedicated Enterprise plan," with Bubble signing a BAA and running the app "on dedicated, HIPAA-ready infrastructure." Bubble's HIPAA FAQ also says "On HIPAA environments, Agent data access stays off, so patient data is never sent to the AI," and "Any third-party service that receives PHI from your app needs its own signed BAA with you."
>
> The points made above about control still apply. Plugins, API connectors, logging and backups are where most gaps show up, so map every service PHI touches before go-live. A WeWeb + Xano stack with BAAs in place is still a valid option for teams not on Dedicated.
>
> Dated notes on Bubble's terms: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/is-bubble-hipaa-compliant/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes that page.

---

## 6. Bubble forum: "Seeking Expert Bubble AI Engineer for… Healthcare Platform" (clinician asks for a HIPAA-compliant build)
- **URL:** https://forum.bubble.io/t/seeking-expert-bubble-ai-engineer-for-revolutionary-healthcare-platform-genesis-protocol-intelligence/377005
- **Date:** 2025-07-28
- **Question (short quote):** "What We're Building: A HIPAA-compliant healthcare platform that helps practitioners assess patients… Required Skills: … HIPAA compliance knowledge"
- **Status:** draft-not-posted. *This is a hiring thread. Post only if the approver judges an answer welcome there (see notes).*

**Draft answer:**
> Not applying for the role, just an update for anyone scoping a similar build, since several replies here said Bubble can't do HIPAA. That changed: Bubble's Support Center (dated October 21, 2026; checked 2026-11-26) says "HIPAA and BAA support is available as an add-on to Bubble's Dedicated Enterprise plan," and that "any third-party service that receives PHI from your app needs its own signed BAA with you."
>
> For a platform with patient questionnaires, scoring and doctor–patient messaging, that means: (1) a Bubble plan where Bubble signs a BAA, or else no real PHI in Bubble; (2) a BAA from every other service the data touches (messaging/SMS, email, file storage, any AI model used for recommendations); (3) privacy rules and an access/audit design reviewed before launch. Any developer you hire should be able to walk you through that list.
>
> Layer-by-layer checklist: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/stack-checker/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes this checker.

---

## 7. Bubble forum: "Looking for a developer for my medical school project" (HIPAA raised in replies)
- **URL:** https://forum.bubble.io/t/looking-for-a-developer-for-my-medical-school-project/371065
- **Date:** 2025-05-28; HIPAA reply 2025-06-06
- **Question (short quote):** the project collects "user-specific data—such as age, sex, medical history, and family history". The reply raised: "Bubble is not hipaa compliant and cannot be made hipaa compliant by using a third party database".
- **Status:** draft-not-posted. *Hiring thread. Approver judgment needed.*

**Draft answer:**
> Two things worth knowing before you build. First, HIPAA may not apply to a student MVP. It covers healthcare providers, plans and clearinghouses and their business associates, not every app that holds health information. If you're outside the US it doesn't apply at all, though your local privacy law will. Check with your school.
>
> Second, if it does apply later (say a clinic pilots it), Bubble now has a route: its Support Center (dated October 21, 2026; checked 2026-11-26) says "HIPAA and BAA support is available as an add-on to Bubble's Dedicated Enterprise plan," and "any third-party service that receives PHI from your app needs its own signed BAA with you." Until then, build and demo with invented patients only.
>
> Dated notes on Bubble: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/is-bubble-hipaa-compliant/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes that page.

---

## 8. Bubble forum: "Looking to develop a presentation prototype of an online doctor–patient platform on Bubble"
- **URL:** https://forum.bubble.io/t/looking-to-develop-a-presentation-prototype-of-an-online-doctor-patient-platform-on-bubble/384051
- **Date:** 2025-10-27 (HIPAA raised in a reply the same day)
- **Question (short quote):** reply: "Just FYI, if this is in the US. Bubble is not HIPPA compliant."
- **Status:** draft-not-posted. *Hiring thread. Approver judgment needed.*

**Draft answer:**
> For an investor-demo prototype with invented patients, HIPAA isn't the blocker. No real PHI means nothing to protect yet. Keep it that way: fake names, fake sessions, no real VR session data.
>
> If the platform goes live in the US with real patients, Bubble's position has changed since that reply. Its Support Center (dated October 21, 2026; checked 2026-11-26) says "HIPAA and BAA support is available as an add-on to Bubble's Dedicated Enterprise plan… Bubble signs a BAA with you," and that "any third-party service that receives PHI from your app needs its own signed BAA with you." Plan the production stack with that in mind, especially messaging, video and any AI features.
>
> Dated notes on Bubble: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/is-bubble-hipaa-compliant/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes that page.

---

## 9. Softr community: "HIPAA Compliance, please"
- **URL:** https://community.softr.io/t/hipaa-compliance-please/16808
- **Date:** 2026-08-04
- **Question (short quote):** "Softr, this has been asked many times - HIPAA compliance. There is a whole world of apps waiting to be built for patient portals, clinical workflows…"
- **Status:** draft-not-posted

**Draft answer:**
> For anyone reading this later: Softr's docs answer this directly. Its "HIPAA Compliance" page (checked 2026-11-26) says: "Softr is not HIPAA-compliant and does not sign Business Associate Agreements (BAAs)." It also spells out the consequence: PHI "cannot be transmitted to or stored inside Softr — not in a connected data source row, not in a form submission, not in a file upload, not in the Users table, and not in a workflow payload."
>
> The pattern Softr describes: keep PHI in a backend that has signed a BAA with you, have Softr read only a non-identifying view, and render any real PHI from the compliant system, for example in an embed. Watch logins in particular: Softr's page notes that patient emails in the Users table are themselves identifiers, so either limit Softr logins to staff or put authentication behind an identity provider that has a BAA with you.
>
> Dated Softr notes: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/is-softr-hipaa-compliant/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes that page.

---

## 10. Vercel community: "Best Strategies to Deploy a HIPAA-Compliant Healthcare App on Vercel"
- **URL:** https://community.vercel.com/t/best-strategies-to-deploy-a-hipaa-compliant-healthcare-app-on-vercel/17212
- **Date:** 2025-07-28 (Vercel reply update 2025-09-09)
- **Question (short quote):** how to make a healthcare app "secure enough to protect patient information" and meet "regulations like HIPAA"
- **Status:** draft-not-posted. *I could not confirm from the page whether replies are still open.*

**Draft answer:**
> Adding detail for anyone who built the front end with v0. Hosting and v0 are covered differently.
>
> Hosting: Vercel's changelog (Sept 9, 2025; checked 2026-11-26) says "Pro teams can now enter into a Business Associate Agreement (BAA)… The BAA is available self-serve through the dashboard with no Enterprise contract required," and "Compliance is a shared responsibility."
>
> v0: Vercel's AI Product Terms (last updated March 17, 2026; checked 2026-11-26) say: "You must not include any sensitive personal information (such as health information…) in your Input." So build and debug in v0 with invented patients, then deploy the code to a team that has the BAA.
>
> Then put a BAA in place with every other layer that touches PHI: database, auth, email/SMS, logging and any LLM API. Vercel's BAA covers Vercel only.
>
> Dated breakdown: https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/is-vercel-hipaa-compliant/
>
> Disclosure: I work with Palo Alto Health Labs, which publishes that page.

---

## Vendor quotes used (all checked on the vendor's own page, 2026-11-26)

| Vendor | Page | Quote used |
|---|---|---|
| Replit | https://replit.com/build/therapy-website-builder | "Replit does not sign BAAs for its standard hosting services, so it is not a HIPAA-compliant builder out of the box." / "You cannot use Replit's standard deployment for websites that handle PHI." |
| Replit | https://docs.replit.com/features/security/shared-responsibility-model | "Regulatory compliance of your application … Meeting laws and regulations applicable to your app (for example, GDPR, CCPA, PHI, PCI DSS, HIPAA, SOC 2). … You" |
| Bubble | https://bubble.io/support/en/articles/8525403-is-bubble-hipaa-compliant (dated Oct 21, 2026) | "HIPAA and BAA support is available as an add-on to Bubble's Dedicated Enterprise plan. With it, Bubble signs a BAA with you and runs your app on dedicated, HIPAA-ready infrastructure." / "any third-party service that receives PHI from your app needs its own signed BAA with you." |
| Bubble | https://bubble.io/support/en/articles/10775869-hipaa (dated Oct 21, 2026) | "On HIPAA environments, Agent data access stays off, so patient data is never sent to the AI." / "Any third-party service that receives PHI from your app needs its own signed BAA with you." |
| Bubble (older manual, conflicts with the above) | https://manual.bubble.io/help-guides/infrastructure/compliance/hipaa | "Bubble cannot support HIPAA compliant apps." |
| Softr | https://docs.softr.io/security/hipaa-compliance | "Softr is not HIPAA-compliant and does not sign Business Associate Agreements (BAAs)." |
| Vercel | https://vercel.com/changelog/hipaa-baas-are-now-available-to-pro-teams (Sept 9, 2025) | "Pro teams can now enter into a Business Associate Agreement (BAA)… available self-serve through the dashboard with no Enterprise contract required." |
| Vercel | https://vercel.com/legal/ai-product-terms (last updated Mar 17, 2026) | "You must not include any sensitive personal information (such as health information, …) in your Input." |

## Notes
- Threads 6, 7 and 8 are hiring threads where HIPAA came up. An affiliated answer there may read as promotional. Lower priority, approver's call.
- Thread 5 is from an agency that markets its own stack (with referral links). The draft avoids criticising it.
- Thread 10: the Vercel staff replies already answer the hosting side. The draft adds the v0 distinction only. Lower priority.
