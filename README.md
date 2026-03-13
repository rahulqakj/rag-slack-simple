# QA Assistant with Feedback-aware Memory

A comprehensive Streamlit-based QA Assistant that uses Gemini AI for intelligent question answering with multi-source context retrieval, chat memory, and feedback-aware responses.

## 🚀 Features

### Core Features
- **Multi-Source Knowledge Retrieval**: Search across uploaded documents, Notion, Jira, and web sources
- **Feedback-Aware Memory**: Learn from user feedback to improve future responses
- **Chat Memory**: Persistent conversation history stored in PostgreSQL
- **File Upload Support**: PDF, TXT, DOCX, CSV files with automatic chunking and embedding
- **Real-time Analytics**: Track usage patterns, feedback rates, and source utilization

### External Integrations
- **Notion API**: Search and retrieve content from Notion workspaces
- **Jira API**: Find relevant issues and project information
- **Web Search**: Fallback search using DuckDuckGo for additional context

### Advanced Features
- **Context Assembly**: Intelligent combination of multiple information sources
- **Feedback Loop**: User ratings (👍 Good / 👎 Not Good) with detailed notes
- **Analytics Dashboard**: Visual insights into system performance and usage
- **Session Management**: Persistent chat sessions with memory retrieval

## 🏗️ Architecture

```
[Streamlit UI] → [Query Processing] → [Multi-Source Retrieval]
                                           ↓
[PostgreSQL + pgvector] ← [Context Assembly] ← [External APIs]
                                           ↓
[Gemini LLM] → [Response Generation] → [Feedback Collection]
                                           ↓
[Analytics Storage] → [Dashboard Visualization]
```

## 🛠️ Tech Stack

- **Frontend**: Streamlit
- **LLM & Embedding**: Google Gemini API (gemini-1.5-pro + models/embedding-001)
- **Database**: PostgreSQL + pgvector extension
- **External APIs**: Notion, Jira, Web Search
- **File Processing**: PyPDF2, python-docx, pandas
- **Analytics**: Plotly for data visualization

## 📋 Prerequisites

1. **Python 3.8+**
2. **PostgreSQL 12+** with pgvector extension
3. **Google Gemini API Key**
4. **Optional**: Notion Integration Token, Jira API Credentials

## 🚀 Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd qa-streamlit-app
   ```

2. **Configure environment**
   ```bash
   cp config/env/.env.example .env
   # Edit .env with your actual credentials
   ```

3. **Install dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Set up PostgreSQL with pgvector**
   - Docker: `docker-compose up streamlit-db -d`
   - Local: create DB + enable pgvector, then run:
     ```sql
     psql -U qa_user -d qa_assistant -f migrations/migration.sql
     ```

5. **Run the application**
   ```bash
   streamlit run app.py
   ```

## ⚙️ Configuration

### Required Environment Variables
```bash
# Gemini API
GOOGLE_API_KEY=your_gemini_api_key

# PostgreSQL Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=qa_assistant
DB_USER=your_username
DB_PASSWORD=your_password
```

### Optional Environment Variables
```bash
# Notion Integration
NOTION_TOKEN=your_notion_token

# Jira Integration
JIRA_SERVER=https://your-domain.atlassian.net
JIRA_EMAIL=your_email@company.com
JIRA_API_TOKEN=your_jira_token
```

## 🧭 Project Structure

```
qa-streamlit-app/
├── app.py                  # Streamlit entry point with auth + navigation
├── requirements.txt        # Python dependencies
├── migrations/             # Database schema assets
│   └── migration.sql       # pgvector + app tables
├── config/
│   └── env/.env.example    # Environment variables template
├── run.sh                  # Local bootstrap script (ignored in VCS)
├── Dockerfile              # Container image build
├── docker-compose.yml      # Local stack (app + Postgres + worker)
├── scripts/                # Deploy helpers
│   └── deploy_to_vps.sh
├── src/
│   ├── config/             # DB + API configs
│   ├── core/               # Embeddings, LLM, knowledge, chat, analytics, jobs
│   ├── api/                # Gemini web search
│   ├── ui/                 # Streamlit pages
│   ├── utils/              # File + Slack helpers
│   ├── scripts/            # Slack ingest/export CLIs
│   └── workers/            # Slack ingest worker
```

## 📖 Usage

### 1. Chat Interface
- Ask questions in natural language
- System automatically searches multiple sources
- View sources used for each response
- Provide feedback on answer quality

### 2. Upload Knowledge Base
- Upload PDF, TXT, DOCX, or CSV files
- Files are automatically chunked and embedded
- Content becomes searchable in future queries

### 3. Analytics Dashboard
- View feedback statistics and trends
- Monitor source usage patterns
- Track daily query volumes
- Analyze response quality over time

### 4. Settings
- Check API connection status
- View configuration requirements
- Monitor system health

## 🔄 Workflow

1. **Query Processing**
   - User submits question
   - Query is embedded using Gemini
   - Similarity search across knowledge base

2. **Multi-Source Retrieval**
   - Local knowledge base (pgvector)
   - Notion pages and databases
   - Jira issues and projects
   - Web search results

3. **Context Assembly**
   - Combine relevant information
   - Include chat memory
   - Add feedback warnings for similar queries

4. **Response Generation**
   - Gemini LLM processes assembled context
   - Generates comprehensive answer
   - Considers previous feedback

5. **Feedback Collection**
   - User rates response quality
   - Feedback stored for future reference
   - Analytics updated

## 📊 Database Schema

### Tables
- **knowledge_chunks**: Document chunks with embeddings
- **chat_history**: Conversation history with embeddings
- **feedback**: User feedback with detailed notes
- **analytics**: Usage statistics and performance metrics

### Key Features
- Vector similarity search with pgvector
- JSONB metadata storage
- UUID primary keys
- Timestamp tracking

## 🎯 Use Cases

### QA Engineering Teams
- Quick access to documentation
- Bug report analysis
- Test case reference
- Knowledge sharing

### Development Teams
- Code documentation search
- API reference lookup
- Project management integration
- Technical decision tracking

### Support Teams
- FAQ automation
- Issue resolution guidance
- Knowledge base maintenance
- Customer query analysis

## 🔧 Customization

### Adding New Data Sources
1. Implement search function in `app.py`
2. Add to context assembly logic
3. Update analytics tracking
4. Configure environment variables

### Modifying Response Generation
1. Edit `ask_gemini()` function
2. Adjust prompt engineering
3. Modify context assembly
4. Update feedback processing

### Extending Analytics
1. Add new metrics to analytics table
2. Create visualization functions
3. Update dashboard interface
4. Implement data export features

## 🚨 Troubleshooting

### Common Issues
1. **Database Connection**: Check PostgreSQL credentials and pgvector extension
2. **API Limits**: Monitor Gemini API usage and rate limits
3. **File Upload**: Ensure supported file formats and size limits
4. **External APIs**: Verify Notion/Jira credentials and permissions

### Performance Optimization
1. **Chunk Size**: Adjust text chunking parameters for optimal retrieval
2. **Cache**: Implement response caching for frequent queries
3. **Indexing**: Optimize database indexes for vector similarity search
4. **Batching**: Process multiple files in batches

## 📈 Roadmap

### Phase 1: MVP ✅
- Basic chat interface
- File upload and processing
- Feedback collection
- Analytics dashboard

### Phase 2: Enhanced Integrations
- Advanced Notion database queries
- Jira workflow integration
- Slack/Teams notifications
- Email integration

### Phase 3: Advanced Features
- Multi-language support
- Custom knowledge graphs
- Advanced analytics
- API endpoints

### Phase 4: Enterprise Features
- User authentication
- Role-based access
- Audit logging
- Advanced security

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Implement changes
4. Add tests
5. Submit pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:
- Create an issue in the repository
- Check the troubleshooting section
- Review the documentation
- Contact the development team
