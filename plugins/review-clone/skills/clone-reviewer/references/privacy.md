# clone-reviewer: privacy notice (Step 2)

`collect.py check` prints `{"visibility": "public|private|internal", "private": bool, "can_read": bool}`. A failure means your `gh` login cannot read the repo (no access, wrong name): stop and show the error.

Print the notice for the visibility, then continue; it never blocks.

- **public**
  > 🔔 This will derive a persona from <handle>'s **public** GitHub review comments. They will not be notified. A disclaimer line stating the derived nature will be written into PERSONA.md.
- **private** or **internal**
  > 🔒 `<repo>` is **<visibility>**. Its comments and diff hunks are stored only on this machine, in the persona dir (owner-only permissions: 0700 dirs, 0600 files), and the persona is marked `private_source` with a matching disclaimer. Do not share it. The people named have not been notified. Step 8 offers to delete the raw scrape.

Private data stays out of the repo: nothing is written inside the checkout.
