# 🤖 AI-Powered API Generator

A fully automated platform that generates and deploys custom APIs using AI. Users describe their desired API functionality in plain text, and GPT-4o generates the backend code automatically.

## ✨ Features

- **Natural Language API Generation**: Describe your API in plain text
- **Instant Deployment**: Generated APIs are immediately available via REST endpoints
- **Security First**: Comprehensive code validation and sandboxing
- **Beautiful UI**: Modern, responsive web interface
- **File Processing**: Support for file uploads and processing
- **Live Testing**: Built-in API testing interface
- **Auto Documentation**: GPT-generated docs and curl examples

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- OpenAI API key

### Local Development

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd AI-Powered-API-Generator
   ```

2. **Set up virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp env_example.txt .env
   # Edit .env and add your OpenAI API key
   ```

5. **Run the application**
   ```bash
   python main.py
   ```

6. **Open your browser**
   ```
   http://localhost:8000
   ```

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   FastAPI       │    │   OpenAI        │
│   (HTML/JS)     │───▶│   Backend       │───▶│   GPT-4o        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                               │
                               ▼
                       ┌─────────────────┐
                       │  Generated APIs │
                       │  (File Storage) │
                       └─────────────────┘
```

### Core Components

- **Frontend**: Modern HTML/CSS/JS interface with Tailwind CSS
- **Backend**: FastAPI application with async/await support
- **AI Integration**: OpenAI GPT-4o for code generation and documentation
- **Security Layer**: Multi-level code validation and sandboxing
- **File Storage**: Simple file-based storage for generated APIs
- **Dynamic Execution**: Runtime loading and execution of generated code

## 📡 API Endpoints

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Frontend interface |
| `GET` | `/health` | Health check |
| `POST` | `/generate-api` | Generate new API |
| `POST` | `/api/{user_id}/{api_slug}` | Execute generated API |
| `GET` | `/api/{user_id}` | List user's APIs |
| `DELETE` | `/api/{user_id}/{api_slug}` | Delete API |

### Example: Generate API

```bash
curl -X POST "http://localhost:8000/generate-api" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Extract names and email addresses from uploaded text files",
    "sample_input": "A text file with contact information",
    "expected_output": "JSON with extracted names and emails",
    "user_id": "john_doe",
    "api_name": "contact_extractor"
  }'
```

### Example: Execute API

```bash
curl -X POST "http://localhost:8000/api/john_doe/contact_extractor" \
  -F "file=@contacts.txt"
```

## 🔒 Security Features

### Code Validation
- **Forbidden Keywords**: Blocks dangerous imports and functions
- **AST Analysis**: Parses code for malicious constructs
- **Pattern Matching**: Regex-based detection of unsafe patterns
- **Import Restrictions**: Only allows safe built-in libraries

### Allowed Libraries
- `json`, `re`, `datetime`, `math`, `base64`, `hashlib`
- `typing`, `collections`, `itertools`, `functools`
- `string`, `random`, `time`, `calendar`, `decimal`

### Blocked Operations
- File system access (`os`, `sys`, `subprocess`)
- Network requests (`requests`, `urllib`)
- Code execution (`eval`, `exec`, `compile`)
- Dynamic imports and reflection

## 🚀 Deployment

### Railway Deployment

1. **Connect to Railway**
   ```bash
   railway login
   railway link
   ```

2. **Set environment variables**
   ```bash
   railway env set OPENAI_API_KEY=your_key_here
   ```

3. **Deploy**
   ```bash
   railway up
   ```

### Docker Deployment

1. **Build image**
   ```bash
   docker build -t ai-api-generator .
   ```

2. **Run container**
   ```bash
   docker run -p 8000:8000 -e OPENAI_API_KEY=your_key ai-api-generator
   ```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o | Yes |
| `ENVIRONMENT` | Environment (development/production) | No |

## 💡 Usage Examples

### 1. Text Processing API
```
Prompt: "Count word frequency in uploaded text files"
Result: API that accepts text files and returns word count statistics
```

### 2. Data Validation API
```
Prompt: "Validate email addresses and phone numbers in JSON data"
Result: API that validates contact information format
```

### 3. File Conversion API
```
Prompt: "Convert CSV data to structured JSON format"
Result: API that transforms CSV uploads to JSON
```

## 🛠️ Development

### Project Structure
```
AI-Powered-API-Generator/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration settings
│   ├── models.py            # Pydantic models
│   └── services/
│       ├── openai_service.py    # OpenAI integration
│       ├── security_service.py  # Code validation
│       └── file_service.py      # File management
├── generated_apis/          # Generated API storage
├── templates/
│   └── index.html          # Frontend interface
├── static/                 # Static assets
├── requirements.txt        # Dependencies
├── Dockerfile             # Container configuration
├── railway.toml           # Railway deployment config
└── main.py               # Application entry point
```

### Adding New Features

1. **New Service**: Add to `app/services/`
2. **New Endpoint**: Add to `app/main.py`
3. **New Model**: Add to `app/models.py`
4. **Frontend Changes**: Modify `templates/index.html`

## 🔧 Configuration

### Security Settings
```python
FORBIDDEN_KEYWORDS = {
    "os", "subprocess", "eval", "exec", "requests", 
    "urllib", "socket", "import", "__import__"
}
```

### File Limits
```python
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
```

## 🐛 Troubleshooting

### Common Issues

1. **OpenAI API Key Error**
   - Ensure your API key is valid and has sufficient credits
   - Check that the environment variable is set correctly

2. **Generated API Not Found**
   - Verify the user_id and api_slug are correct
   - Check that the API was successfully generated and saved

3. **Code Validation Errors**
   - Review the forbidden keywords list
   - Ensure generated code follows security guidelines

### Debug Mode
```bash
# Enable debug logging
export LOG_LEVEL=debug
python main.py
```

## 📈 Performance

- **Generation Time**: ~5-15 seconds per API
- **Execution Time**: ~100-500ms per request
- **File Size Limit**: 10MB
- **Concurrent Users**: Scales with server resources

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- OpenAI for GPT-4o API
- FastAPI for the excellent web framework
- Tailwind CSS for beautiful styling

---

**Built with ❤️ by the AI API Generator team** 