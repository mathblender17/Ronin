# Ronin - Topic Research CLI

Ronin is a simple, educational command-line interface (CLI) application built in Python that generates structured, multi-dimensional markdown research reports on any topic using a single call to the Gemini API (`gemini-2.5-flash`).

This project is optimized for simplicity, readability, and educational value.

---

## 1. Folder Structure

```text
Ronin/
├── .env                  # Environment variables (API keys)
├── .gitignore            # Git ignore file
├── README.md             # Project documentation and setup instructions
├── main.py               # Main CLI application code
├── requirements.txt      # Python dependencies
└── outputs/              # Directory where generated reports are saved
    └── example_report.md  # Example markdown report
```

---

## 2. Requirements (`requirements.txt`)

The project uses only two lightweight libraries:
* `google-genai`: The official, modern Google Gemini API SDK.
* `python-dotenv`: Loads configuration values from a `.env` file into system environment variables.

To install them:
```bash
pip install -r requirements.txt
```

---

## 3. Setup Instructions

### Step 1: Install Python
Ensure Python 3.9 or higher is installed on your system.

### Step 2: Configure Environment Variables
Create a file named `.env` in the root of the project (if it doesn't already exist) and add your Gemini API key:
```env
GEMINI_API_KEY=your_actual_api_key_here
```

### Step 3: Install Dependencies
Run the following command in your terminal:
```bash
pip install -r requirements.txt
```

### Step 4: Run the Application
Start the CLI application:
```bash
python main.py
```

---

## 4. Step-by-Step Execution Flow

1. **Environment Initialization:** When `main.py` is executed, `load_dotenv()` runs first to read the `.env` file and load `GEMINI_API_KEY` into the system environment.
2. **Client Authentication:** The application calls `initialize_client()`, which retrieves the API key and initializes a `genai.Client` connection.
3. **User Prompt:** The CLI prompts the user to enter a research topic.
4. **Structured Generation:** `generate_report()` takes the topic and sends a structured prompt to the Gemini API using the `gemini-2.5-flash` model.
5. **Sanitization & Save:** The application sanitizes the topic string to make it a safe filename and saves the raw markdown response from the model into the `outputs/` folder.
6. **Execution Output:** The program prints the saved path to the console and exits.
