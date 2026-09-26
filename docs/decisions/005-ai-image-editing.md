# ADR 005: AI photo editing and image rights

- **Status:** Accepted. Alireza asked for all five edits now, on 2026-09-27. The reference-image rule below was proposed by Claude and is pending his confirmation.
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

### Switches
- Five switches live in the brand profile under `image_editing`. **All are off by default**, and only owners and admins can turn them on.
- The API refuses a disabled edit (403). The panel shows only the enabled ones.

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
| `render`: a visualisation (renders; AI background, recolour or swap) | yes, but the text must not present it as a finished client project |
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
- The Copywriter must know the source of the photo it writes for, so that a render is never called a finished project. This is wired in step 5, when briefs are built from library photos.
