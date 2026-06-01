# STYLE.md

How to write good Python code in this repository.

The whole point of the style is this: someone using your code should be able to treat it like a black box. They put something in, they get something out, and they never have to look inside to understand it or babysit it while it runs. Your code can do plenty of complicated work on the inside — that complication just shouldn't spill out onto the person calling it.

Use these rules whenever you write or change a function that other code will call.

**Use plain functions, not objects that remember things.** Write the work as ordinary functions that take data in and hand new data back. The only classes you write are small holders for data (see "Be exact about the data, in and out"); they just carry data and contain no logic. Nothing is remembered from one call to the next. If you catch yourself reaching for a class with methods, or an object you set up once and reuse, stop — the rules below come first.

## Expose one function, hide the rest

Each piece of work is one function that callers use, plus any helper functions it needs on the inside. Keep what's visible small: start helper names with an underscore (`_split`), and list only the main function in `__all__` so it's the single thing other code can import. The caller imports one name; everything else stays out of reach.

```python
__all__ = ["document_to_summary"]

def document_to_summary(document: Document, config: SummaryConfig) -> Summary:
    chunks = _split(document)
    ...

def _split(document: Document) -> list[Chunk]:
    ...
```

## Start from the inputs and outputs

Before writing anything, decide what the function takes and what it gives back. The caller hands something over and gets the expected thing in return; the steps in between are not their concern.

Name the function so the name tells you both. Use `input_to_output` names — `image_to_embedding`, `document_to_summary` — instead of vague verbs like `process`, `run`, or `handle`. If someone has to open the code to find out what comes back, the name has failed.

When a function takes more than one thing, name it after the main input and output, not every argument: `document_to_summary`, not `document_and_config_to_summary`. Settings and other supporting pieces stay out of the name.

## Be exact about the data, in and out

Don't make callers deal with vague, free-form data. Don't take in or return plain dictionaries, tuples, or loose bundles of values. Use Pydantic models — small classes that spell out the exact shape of your data and check it for you. Then the agreement is written down, the data is checked the moment it arrives, and callers get editor autocomplete and type checking instead of guesswork.

Set these data models so they can't be changed after they're created. That turns the "don't change the data passed in" rule below into something automatic instead of something you have to remember.

```python
class Embedding(BaseModel):
    model_config = ConfigDict(frozen=True)   # can't be changed once created
    ...

class Classification(BaseModel):
    model_config = ConfigDict(frozen=True)
    ...

def embedding_to_classification(embedding: Embedding) -> Classification:
    ...
```

## Put settings in one object

When a function needs settings, pass one settings object instead of a long list of separate arguments. Pass in anything else the function needs while it runs the same way — a model client, a connection to a service — so everything it relies on is right there at the call.

Build the invariants — the rules that must always hold — into the settings themselves, so a bad combination simply can't be created in the first place, rather than checking by hand afterward. Use the built-in checks: `gt=0` (must be greater than zero), values that can't be infinity or "not a number", ranges with a floor and a ceiling. And when a handful of true/false flags really come down to one choice, replace them with a single named set of options (an enum).

```python
class Mode(str, Enum):
    FAST = "fast"
    ACCURATE = "accurate"

class ClassifyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_size: int = Field(gt=0)
    threshold: float = Field(gt=0, allow_inf_nan=False)
    mode: Mode = Mode.ACCURATE
```

## Handle two kinds of failure differently

Being called the wrong way and running into a bad piece of data are different problems, and they need different responses.

**If the code is used wrong, stop right away.** A wrong type, a missing required setting, an argument that makes no sense — these are mistakes in the calling code, so raise an error immediately and make it impossible to miss.

**If a single piece of data is bad, keep going.** A function working through many items in a row shouldn't blow up halfway and throw away everything it already finished. When one item is malformed or unreadable, note the problem and move on to the next.

**Hand the bad-data problems back; don't only write them to the log.** When you work through a group of items, gather each failure and return it together with the successes, so the calling code can respond to failures in code instead of by reading log messages. Still write a log warning so a person can see it (use `logging.warning`, never `print`), but the version the code can act on goes in what you return. Give each problem a clear named reason from a fixed list, and point to the exact item that failed, so the caller can find and fix it.

```python
class ErrorCode(str, Enum):
    DUPLICATE_ID = "duplicate_id"
    MISSING_METADATA = "missing_metadata"

class ItemError(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: ErrorCode
    item_id: str          # which item went wrong
    detail: str

class BatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    classifications: list[Classification]
    errors: list[ItemError]

def embeddings_to_classifications(
    embeddings: list[Embedding], config: ClassifyConfig
) -> BatchResult:
    results, errors = [], []
    for item in embeddings:
        try:
            results.append(_classify(item, config))
        except DataError as e:                 # only the data problems you expect
            logging.warning("skipping %s: %s", e.item_id, e.code)
            errors.append(ItemError(code=e.code, item_id=e.item_id, detail=str(e)))
    return BatchResult(classifications=results, errors=errors)
```

**Catch only the problems you expect, so you don't hide real bugs.** When you skip a bad item, catch only the specific data problems you planned for — never a catch-all `except`. Raise those expected problems as their own clearly-named error (here `DataError`, which carries the reason and the failing item) that the loop turns into a returned `ItemError`. Real bugs in your own code — dividing by zero, stepping one past the end of a list — are not the caller's job to handle; let them break through so you catch and fix them while testing. A catch-all `except` quietly turns those bugs into warnings, which is exactly what you must not let happen.

```python
# ❌ hides real bugs by treating them like bad data
for item in embeddings:
    try:
        results.append(_classify(item, config))
    except Exception as e:
        logging.warning("skipping item: %s", e)

# ✅ only data problems are skipped; everything else breaks through
for item in embeddings:
    try:
        results.append(_classify(item, config))
    except DataError as e:
        errors.append(ItemError(code=e.code, item_id=e.item_id, detail=str(e)))
```

## Statelessness and purity

Functions should be stateless and pure. Stateless means a function carries nothing over from one call to the next; pure means its result depends only on what you pass in. Together those make the function deterministic — the same inputs always give the same result — and concurrency-safe by construction, so you can safely run many calls at the same time.

Don't change the data passed in — build and return new data instead. And don't lean on anything the caller can't see: no global variables, no shared objects sitting at the top of a file, nothing the function quietly reaches for in the background.

Doing real work like loading a model or calling a service is fine. The rule is just that those things are passed in as arguments — usually on the settings object — never grabbed from a global. A model client you pass in is visible and easy to swap out; a model client pulled from a global is hidden.

```python
# ❌ hidden: the caller can't see it and can't swap it out
_CLIENT = load_model()

def image_to_embedding(image: Image) -> Embedding:
    return Embedding.from_raw(_CLIENT.encode(image))

# ✅ passed in: visible, and easy to replace in a test
def image_to_embedding(image: Image, config: EmbedConfig) -> Embedding:
    return Embedding.from_raw(config.client.encode(image))
```

This is also what keeps the code easy to test. A pure function that only reshapes data can be tested directly. A function that calls out to something stays testable for the same reason its needs are visible: pass in a stand-in client and the result becomes deterministic — there's no global to monkeypatch, and no setup or teardown between tests.

## Quick checklist

Before you call a function finished, check:

- The main function is named `input_to_output`, and the name says what comes back.
- One public function for callers; helpers start with `_`, and only the main one is in `__all__`.
- Inputs and outputs are Pydantic models, not plain dictionaries or tuples, and they can't be changed after they're created.
- Settings live in one object, with the limits built in and stacked true/false flags replaced by named options where they come down to one choice.
- Things like model clients and service connections are passed in, not grabbed from globals.
- Being called wrong raises an error right away; bad data is collected (with a named reason and the failing item) and returned, not just logged.
- The loop catches only the data problems you expect; real bugs are left to break through.
- The function is stateless and pure: it doesn't change its inputs and doesn't rely on anything the caller can't see.