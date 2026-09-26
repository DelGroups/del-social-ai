# ADR 005: AI photo editing and image rights

- **Status:** Accepted, revised the same day. Alireza asked for all five edits now (2026-09-27), then asked that they be configured **per photo** instead of switched on per company. The reference-image rule below was proposed by Claude and is pending his confirmation.
- **Date:** 2026-09-27
- **Phase:** 1 (pulled forward from the Phase 2 Visual Designer)
- **Changes:** docs/agent-team.md, Visual Designer rule "generated furniture must not misrepresent real items" (see Rights)

## Context

The media library (step 4) prepares photos by code only. Alireza wants five AI edits, each of which the company can switch off:

1. change the product's surroundings;
2. remove one or more items;
3. improve quality (resolution, noise, sharpness);
4. change the product's colour without changing its design;
5. replace the product with a similar one.

His answer on 4–5: rendered or AI-altered products are fine as long as they look technically and visually real, and they do not have to be Del Furniture models. He also said that many source photos may be saved from Pinterest.

## Decision

### Per-photo settings (a "recipe")
- **No company-wide switches.** Each photo has its own recipe with five options, each with its own on/off tick and details:
  - enhance;
  - remove (what to remove);
  - background (new surroundings, optionally a reference room);
  - recolor (the new colour or finish);
  - swap (the new product, optionally a reference product image).
  - There is also a "main product" field for the whole recipe.
- **The recipe is saved with the photo** (`media_assets.edit_recipe`) and reused next time.
- **"Apply" makes one new version with everything ticked:**
  - the instruction edits go to the editor model as one combined instruction;
  - enhance runs last, on that result, with fal's output URL chained straight into the next step.
- Anyone who manages media (owner, admin) can apply a recipe. The `image_editing` switches left in old brand profile versions are ignored.

### Models (config, not code)
- **Background, remove, recolour and swap:** one instruction-based editor, `IMAGE_EDIT_MODEL`, default `fal-ai/flux-2-pro/edit`. It takes up to 9 reference images and costs about $0.03 per output megapixel.
- **Quality:** `IMAGE_ENHANCE_MODEL`, default `fal-ai/topaz/upscale/image`, run at 2× with no prompt.
- Both run through the fal.ai queue API with `FAL_KEY`, which is entered on the server only.

### Code decides everything except the pixels
- **The instruction:** code builds it from a fixed template for each kind.
  - It always says to keep the product's shape, construction, materials and details, and to change nothing else.
  - It always says: no text, logos, watermarks or people (CLAUDE.md rule 8).
- **The user's request:** people write it in any language. Haiku translates it to English and only translates. If translation fails, the original text is sent.
- **The input:** a signed 2048 px "full" variant with no crop, no tone change and no metadata.
- **Cost:** computed by code from the output size. An unknown price is recorded as NULL, never guessed. Costs appear in the usage report as "image_editor".

### Lineage and approval
- **Each edit creates a new asset** with `parent_asset_id`, `status` (`pending`, `ready` or `failed`) and `edit` (kind, request, prompt, model, cost, error). The original never changes.
- **An AI edit is usable in posts only after a human approves it** (`approved_at`). The panel shows the image before and after.
- There is no automatic pixel check yet. The human approval is the product check.

### Rights (the `source` of every image)
| Source | Published? |
|---|---|
| `own`: our work | yes |
| `licensed` | yes |
| `render`: a visualisation (renders; AI background, recolour or swap) | yes, with the same confident copy as any post (Alireza, 2026-09-27: no disclaimers, no AI labels) |
| `reference`: someone else's image, e.g. saved from Pinterest | **never**; inspiration only |

Rules applied by code:
- An edit of a reference stays a reference.
- A swap that inserts the product from a reference image is a reference.
- A background, recolour or swap applied to our photo becomes `render`.
- Enhance and remove keep the parent's source.

Why the reference rule exists:
- Publishing another photographer's or brand's image as Del Furniture's is copyright infringement.
- Repeated takedowns can get the page blocked.
- Showing another company's furniture as "ours" also misleads customers.

Using such images as style or product references to edit our own photos is allowed.

## Consequences
- Edits run as background jobs inside the API process. A restart during an edit leaves it `pending`. The queue worker (step 7) will make jobs durable.
- Nothing published carries an AI label or watermark. The "AI" and "Render" badges exist only inside the panel.
- Published images are re-encoded without metadata, so Meta's C2PA/IPTC-based "AI info" label is not triggered by our files. Invisible pixel watermarks that some models embed cannot be ruled out; they will be checked in the model comparison.
