# Model licences — what cat-tape uses and what each licence asks of it

Read verbatim 2026-10-29: the LTX-2.x licence text from `github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x` ("License
date: August 11, 2026"), and the licence fields of the model cards. This repo includes **no weights**. Users download
them from the publishers and accept their licences there.

## LTX-2.5 — LTX-2.x Community License Agreement (Lightricks Ltd.)

Source: https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x · model card `license_name:
ltx-2.x-community-license-agreement` (huggingface.co/Lightricks/LTX-2.5).

The clauses that matter for this app:

- **§2.1 the grant:** use, reproduce, distribute, modify "for any purpose", subject to Attachment A, except that
  "Entities with annual revenues of at least $10,000,000" need a paid licence for anything beyond a Non-Commercial
  Purpose (§2.2). An individual making and sharing cat tapes is not such an Entity.
- **§3 redistribution:** applies to distributing "copies of LTX-2.x or Derivatives of LTX-2.x". cat-tape distributes
  neither the weights nor a modified model. It ships only our own graph files that load them.
- **§4 and Attachment A, use restrictions:** "You shall require all of your users who use LTX-2.x or a Derivative of
  LTX-2.x to comply with the terms of this Section 4." **Users of cat-tape must follow Attachment A and the LTX
  Acceptable Use Policy** (https://static.lightricks.com/legal/ltx-acceptable-use-policy.pdf).
- **Attachment A (5), disclosure:** do not "generate or disseminate information and/or content … and place the
  information and/or content in any context (e.g. bot generating tweets) without expressly and intelligibly
  disclaiming that the information and/or content is machine generated". ⇒ **Say "AI-generated" wherever a tape is
  posted.** Every tape also carries `comment=AI-generated video: …` in its metadata.
- **§6 and Attachment A (19), provenance:** do not remove "metadata, watermarking, content provenance … applied to
  any Output". ⇒ cat-tape carries the source clip's metadata into the finished tape (`-map_metadata 0`,
  `use_metadata_tags`) and adds the AI notice. The LTX-2.5 output we inspected carried only ComfyUI's own
  `prompt` tag (ffprobe, 2026-10-29). ⚠️ Not determined: whether LTX-2.5 embeds an invisible watermark in the
  picture, or whether the VHS grade's noise and blur would degrade one. The licence text names "latent disclosure"
  capabilities but does not say the model applies one.
- **§5 output:** "Licensor claims no rights in the Output you generate using LTX-2.x. You are accountable for input
  you insert into LTX-2.x, the Output you generate and its subsequent uses."
- **Attachment A (7), (20):** no impersonation or deepfakes without consent. Nothing here "directly competes with
  Licensor's commercial products". A single-effect hobby app is the reading we take, stated, not certified.

## ACE-Step 1.5 XL turbo — MIT

Source: model card `license: mit` (huggingface.co/ACE-Step/acestep-v15-xl-turbo, and the family card
huggingface.co/ACE-Step/Ace-Step1.5). The code repository github.com/ace-step/ACE-Step-1.5 `LICENSE` reads "MIT
License · Copyright (c) 2026 ACEStep". ⚠️ The ComfyUI repackage we download from (Comfy-Org/ace_step_1.5_ComfyUI_files)
labels itself `license: apache-2.0`. The upstream publisher's MIT is the one we cite. Both are permissive.

## Z-Image Turbo (the app page's backdrop images only): Apache-2.0

Source: model card `license: apache-2.0` (huggingface.co/Tongyi-MAI/Z-Image-Turbo; ComfyUI repackage
Comfy-Org/z_image_turbo, also Apache-2.0). Used once to render `app/static/den-scene.webp` and `den-wall.webp`
(`backdrop/make_backdrops.py`); not part of the tape pipeline.

## The page font: DejaVu Sans Mono Bold

`app/static/osd.ttf` is DejaVu Sans Mono Bold (Bitstream Vera / DejaVu fonts licence: free to use, modify and
redistribute with the licence notice). It is the same font the tapes' date stamp is drawn in.

## Comfy's own packages

`comfy-sdk` 0.5.0 and `comfy-api-proxy` 0.1.6 (Comfy Org, PyPI): `License-Expression: MIT` in each wheel's METADATA.
