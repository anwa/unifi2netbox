# Applying changes

Only **Apply** writes to NetBox, and only what is checked.

1. [Dry run and apply](01-dry-run-and-apply.md): simulate first, then write
   after one confirmation.
2. [Write order and safeguards](02-write-order-and-safeguards.md): what
   happens during a run and why some rows are skipped.
3. [Write history](03-write-history.md): every run with its results.

A good routine for the first time:

1. Uncheck everything you are unsure about (**Select none** per list).
2. Run a **dry run** and read the results.
3. Apply a small part, for example the networks, then **Refresh**.
4. Continue with interfaces, devices and the rest. After each refresh the
   written rows show *In sync* and a second apply writes nothing.
