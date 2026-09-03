# Status classification edge cases

Use these checks after card histories have been parsed and before writing the monthly sheet.

## `Обнулен` versus `Исчерпан`

`all selected balances == 0` plus `any manual decrease > 0` is **not sufficient** for `Обнулен`. It creates false positives when one card family was consumed naturally and another family had a small administrative decrease.

Assign `Обнулен` only when:

1. the row is in the main block;
2. every selected card has zero current balance;
3. no selected card remains active with a positive balance;
4. **each available card family** was manually reduced (`group_decreased > 0` for an available group family, and `ind_decreased > 0` for an available individual family);
5. the row is not a verified whole-row `Абонемента нет` exception.

Then preserve only actual attendance in effective purchased quantities:

- `Групп = Отходили групп`;
- `Инди = Отходили инди`;
- missing or unused family = `0`.

Examples:

- Group-only card changed `14 → 0`, no write-offs: `Обнулен`.
- Group and individual cards both changed to zero: `Обнулен`.
- Group card naturally consumed to zero; individual card changed `6 → 5` and later consumed to zero: `Исчерпан`, not `Обнулен`.
- All cards naturally consumed, no manual decreases: `Исчерпан`.

## Detailed history versus aggregate visits

When a card history proves whole consultation units but aggregate visit history omits them, use the detailed card history and attach a note. For individual cards, combine fractional write-offs into whole units (for example `0.1 + 0.9 = 1`). For group cards, honor multiplicity markers such as `(x2)`.

## Failed checkpoint retries

A checkpoint containing `search input missing`, `loyalty tab failed`, timeout output, or a process terminated by SIGTERM is not evidence. Retry the same offset in a verified-ready browser target and overwrite the checkpoint only after all rows load. The final merge must validate the expected source-row count, `ok` count, and unresolved history mismatches before apply.