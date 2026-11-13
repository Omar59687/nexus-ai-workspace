# Phase 4 Windows PDF Worker

The experimental document ingestion service routes `.pdf` files through
`IsolatedPdfExtractor` after `read_approved_file()` has resolved and read the
requested file under the configured approved root. The worker receives the
bounded document bytes over stdin; it does not receive the source path. Existing
source paths, SHA-256 version identifiers, and extracted page numbers remain
the responsibility of the ingestion service and document records.

## Windows controls

The Windows runner in `src/nexus_ai/documents/pdf_worker_windows.py` uses only
the Python standard library and Win32 APIs:

- Creates the parser process suspended, assigns it to a newly configured Job
  Object, and resumes it only after assignment succeeds.
- Enforces a per-process and aggregate Job Object memory limit, total Job Object
  user CPU time, and a maximum of 16 active processes.
- Uses `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; timeout, output overflow,
  cancellation, setup errors, and normal completion terminate the full job.
- Enforces a parent wall-clock deadline and checks the bounded stdout collector
  while the worker runs. The parent retains at most the configured output cap.
- Streams input and output in fixed-size blocks. Input byte caps are checked
  before process creation; page-count, per-page text, and total text caps are
  checked inside the parser worker.
- Gives the child only an explicit inherited-handle allowlist for stdin, stdout,
  and stderr redirected to `NUL`.
- Verifies from inside the child that it is running in a Job Object before
  importing `pypdf` or parsing bytes.

If Job Object creation, configuration, process assignment, or worker-side job
verification fails, extraction fails closed. The ingestion service continues
to enforce approved-root path handling before invoking the extractor.

## Security boundary

Job Objects enforce resource limits and process-tree cleanup. They do **not**
restrict filesystem or network access, constrain the process token, or provide a
complete security sandbox. Windows PDF extraction here is bounded local
processing for trusted documents. Processing known hostile or adversarial PDFs
remains unsupported until the worker runs inside a stronger OS isolation
boundary with restricted filesystem and network access. Do not expose this
service through a public or unauthenticated endpoint.

POSIX process limits and the existing POSIX runner are unchanged. PDFs with no
extractable text layer, including scanned image-only PDFs, remain unsupported;
this work adds no OCR and downloads no OCR models.

## Generated-fixture Windows check

From the repository root in PowerShell, run:

```powershell
& .\scripts\verify_windows_pdf_worker.ps1
```

The test module generates PDFs in memory or temporary directories and does not
read owner documents. It exercises normal extraction and provenance, encrypted,
corrupt, empty, page/input limits, timeout, memory exhaustion, output flooding,
descendant cleanup, and concurrent workers. These native Job Object checks must
actually run on Windows; a Linux test result cannot verify Windows enforcement.
