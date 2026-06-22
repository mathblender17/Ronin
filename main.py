import re
import os
from pathlib import Path 
from dotenv import load_dotenv
from google import genai
from google.genai import errors


load_dotenv()

def initialize_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key is None:
        print("[-]ERROR couldn't find the API key")
        print("Please check your .env file and ensure it contains your API key.")
        exit(1)
    return genai.Client(api_key=api_key)


def generate_report(client: genai.Client, topic: str) -> str:
    print(f"[+] Requesting report generation for: '{topic}'")

    prompt = f"""
    You are an expert researcher and analytical thinker.
    Generate a comprehensive, structured research report on the following topic: "{topic}"

    The report MUST contain the following sections, formatted as clear Markdown headings (H2 or H3):
    1. Executive Summary: A concise summary of the topic and key takeaways.
    2. First Principles Breakdown: Deconstruct the topic to its most fundamental truths or building blocks.
    3. Analogies: Provide 1-2 vivid analogies to help a beginner understand this concept.
    4. Assumptions: Highlight common assumptions people make about this topic that might be incorrect.
    5. Steelman View: Present the strongest possible argument in favor of the core concept or its dominant perspective.
    6. Counterargument: Present the strongest criticisms, counter-perspectives, or limitations of this concept.
    7. Synthesis: Reconcile the steelman view and the counterargument into a nuanced conclusion.
    8. Rabbit Holes: Identify 3-4 intriguing questions or sub-topics for further exploration.

    Write in a clear, engaging, and professional tone.
    """

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text
    except errors.APIError as e:
        print(f"[-] Gemini API error: {e}")
        exit(1)
    except Exception as e:
        print(f"[-] An unexpected error occurred during report generation: {e}")
        exit(1)

def sanitize_filename(name: str) -> str:
    clean_name = name.lower().strip()
    clean_name = re.sub(r'\s+','_', clean_name)
    clean_name = re.sub(r'[^\w\-]','',clean_name)
    return clean_name if clean_name else "report"

def save_report(topic: str, content: str) -> Path:
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    filename = f"{sanitize_filename(topic)}.md"
    file_path = output_dir / filename

    with open(file_path, "w", encoding="utf-8") as f :
        f.write(content)
    return file_path

def main():
    print("=========================================")
    print("        RONIN: Topic Research CLI        ")
    print("=========================================")
    client = initialize_client()

    topic = input("\n Enter a topic to research: ").strip()
    if not topic:
        print("[-] Topic cannot be empty. Exiting.")
        return

    report_content = generate_report(client, topic)

    saved_path = save_report(topic, report_content)

    print("\n[+] Report generated successfully!")
    print(f"[+] Saved to: {saved_path.resolve()}")
    print("=========================================")

if __name__ == "__main__":
    main()