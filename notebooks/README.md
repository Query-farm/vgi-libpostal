# Libpostal notebooks

[01 · Normalized address candidates are not confirmed duplicates](01_address_candidates_need_unit_context.ipynb) parses synthetic address records, checks component availability, and reviews building candidates under an explicit apartment-unit policy.

## Native prerequisite

This worker needs the **libpostal C library and its roughly 2 GB of trained data**, which uv cannot install. The saved runs use Homebrew libpostal **1.1.4** on macOS arm64, model data marker **v1**, and pypostal **1.1.11**. A C compiler is needed for the initial Python binding build. Install the library and models first:

```sh
# macOS; this downloads the substantial native model data
brew install libpostal
```

For Linux, follow [libpostal's native installation instructions](https://github.com/openvenues/libpostal#installation), including model data and shared-library configuration. If installed outside compiler defaults, set `LIBPOSTAL_PREFIX` to that installation prefix; configure `ldconfig` or `LD_LIBRARY_PATH` for its `lib` directory as appropriate. The worker is tested here on macOS; the notebook contains no macOS worker path.

`native_support.py` finds `LIBPOSTAL_PREFIX`, or an existing Homebrew prefix, then appends include/lib search paths for uvx's native binding build. On other systems it accepts a library discoverable by the system loader. It does not install the native library, download models, discover a worker checkout or substitute a mock parser. The compiled Python environment is cached by uv. Compiler environment values are restored in cleanup.

The native model is external to the Python lock. Its `data_version` marker is reported when available, but that marker is not a cryptographic identity for the whole model. Different native releases or model data can change labels, expansions and candidate counts. The example checks relationships rather than requiring one model's fixed rankings or counts.

## Run

Install [uv](https://docs.astral.sh/uv/) and Git. Python 3.13–3.14 is required; uv can install it. Initial package, source and extension downloads need internet. After dependencies and models are available, address parsing is local.

```sh
cd notebooks
uv sync --locked
uv run --locked python execute.py --timeout 300
```

Haybarn 2.0.0rc11 uses the literal visible command `uvx --from git+https://github.com/Query-farm/vgi-libpostal@v0.4.0 ... vgi-libpostal-worker`. The tag resolves to `10b31469dec9dd57ec4da6604f095824c23a2164`; explicit worker pins are vgi-python 0.51.0, vgi-rpc 0.53.1, postal 1.1.11 and pyarrow 25.0.1. No local worker checkout or account credentials are required. Upgrade the Git/native pins deliberately and rerun both policies. A cold worker may take tens of seconds to load its models.

Optional editor kernel:

```sh
uv run --locked python -m ipykernel install --user --name vgi-libpostal-notebooks --display-name "Python (vgi-libpostal notebooks)"
```

Use this directory as working directory and Restart Kernel → Run All. The runner creates a temporary kernel, saves outputs only when every cell succeeds, and preserves the previous successful default on failure.

## Experiment

```sh
uv run --locked python execute.py --parameters '{"REQUIRE_UNIT_MATCH":false}' --output-dir artifacts/without-unit-rule
```

Restore `True` for the default. Overrides require a separate destination. The helper, lock, docs and branding accompany the executed copy. Generated experiments, images, logs and environments are ignored.

## Inputs and interpretation

All twelve SQL input records are synthetic teaching records, not private customers, occupants or a verified address directory. Country codes are supplied source context, not inferred country labels. Raw text and IDs remain visible. NULL, blank and incomplete nonempty inputs stay distinct; missing components never become matching empty keys.

Candidates require a parsed house number, road and postcode, matching source country and whitespace-normalized postcode, and at least one shared expansion of house-number-plus-road. Unit expansions are separate. With the default policy, both units must be present and their expansions overlap. Relaxing it retains the same building candidates without unit evidence. This deliberately conservative strict policy also withholds addresses that may legitimately have no unit; it is a policy demonstration, not a universal identity rule.

Libpostal is statistical and returns lowercased labels. Presence counts are not accuracy estimates. MAP parsing retains the last value if a label repeats; use the worker's long-format component function when repeated labels matter. Expansion alternatives carry no confidence score, and an overlapping expansion does not prove identity, deliverability or geographic equality. No records are merged, geocoded or transmitted to an address service. There is no replay/live switch because the worker performs local computation.
