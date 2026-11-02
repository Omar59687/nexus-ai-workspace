
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama


def main() -> None:
    # Connect LangChain to our existing local Ollama model.
    model = ChatOllama(
        model="llama3.2:latest",
        base_url="http://127.0.0.1:11434",
        temperature=0,
        num_predict=128,
    )

    # Define a reusable conversation template.
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a concise technical tutor. "
                "Give accurate and clear explanations.",
            ),
            (
                "human",
                "Explain {concept} in exactly two short sentences.",
            ),
        ]
    )

    # Connect the prompt to the model.
    chain = prompt | model

    # Fill in the variable and call the model.
    response = chain.invoke({"concept": "REST API"})

    print("\nLangChain response:")
    print(response.content)

    print("\nModel:")
    print(response.response_metadata.get("model", "not reported"))


if __name__ == "__main__":
    main()
