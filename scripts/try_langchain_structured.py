
import sys
from collections.abc import Callable

from langchain_ollama import ChatOllama

from nexus_ai.structured_outputs import (
    DEFAULT_REST_EXPLANATION_PROMPT,
    RESTExplanation,
    StructuredOutputRejectedError,
    generate_rest_explanation_with_retry,
)


def main(generate: Callable[[str], RESTExplanation] | None = None) -> None:
    """Run the structured-output demo against local Ollama.

    ``generate`` is injectable so tests can run ``main`` without Ollama.
    A final validation rejection exits with a non-zero status; network
    and programming errors are never classified as rejections.
    """

    if generate is None:
        model = ChatOllama(
            model="llama3.2:latest",
            base_url="http://127.0.0.1:11434",
            temperature=0,
            num_predict=160,
        )

        structured_model = model.with_structured_output(
            RESTExplanation
        )

        def invoke_structured_model(prompt: str) -> RESTExplanation:
            return structured_model.invoke(prompt)

        generate = invoke_structured_model

    attempt_count = 0

    def generate_with_count(prompt: str) -> RESTExplanation:
        nonlocal attempt_count
        attempt_count += 1
        return generate(prompt)

    try:
        result = generate_rest_explanation_with_retry(
            generate=generate_with_count,
            prompt=DEFAULT_REST_EXPLANATION_PROMPT,
        )
    except StructuredOutputRejectedError as exc:
        attempts_used = min(attempt_count, exc.attempts)
        print(f"Rejected: {exc}")
        print(f"Generation attempts used: {attempts_used}")
        sys.exit(1)

    print("Structured response:")
    print(result.model_dump_json(indent=2))
    print(f"\nGeneration attempts used: {attempt_count}")
    print("Semantic validation: PASS")


if __name__ == "__main__":
    main()
