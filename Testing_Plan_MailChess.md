# Testing Plan Document for MailChess Application

**Version:** 1.0
**Date:** November 21, 2025
**Project:** MailChess - Email-based Chess Game Client
**Author:** Development Team

---

## 1) Introduction

### Purpose
This Testing Plan Document outlines the comprehensive testing strategy for the MailChess application, an email-based chess game client that integrates with Gmail to enable users to play chess via email correspondence. The document serves as a guide for ensuring systematic quality assurance throughout the development lifecycle.

### Importance
Testing is critical for MailChess due to its integration with external services (Gmail API, IMAP/SMTP, Stockfish chess engine) and the complexity of managing email threads, chess game state, and user data synchronization. A comprehensive testing plan ensures:
- Reliable email synchronization and thread management
- Accurate chess move validation and game state tracking
- Secure OAuth authentication and data handling
- Optimal performance with incremental sync features

### Agile Methodology Influence
The MailChess project follows Agile development practices with iterative sprints. Testing is integrated throughout each sprint:
- **Continuous Testing:** Tests are written and executed alongside feature development
- **Incremental Coverage:** Each sprint adds new test cases for new features
- **Rapid Feedback:** Quick test cycles enable fast bug detection and resolution
- **User Story Validation:** Acceptance criteria drive test case design

---

## 2) Testing Objectives

### Primary Goals
1. **Functional Correctness:** Verify all features work as specified in user stories
2. **Integration Reliability:** Ensure seamless interaction with Gmail API, IMAP, SMTP, and Stockfish
3. **Data Integrity:** Validate accurate email parsing, chess move tracking, and database consistency
4. **Security Assurance:** Confirm OAuth token handling, session management, and data protection
5. **Performance Optimization:** Verify incremental sync performance improvements
6. **User Experience:** Ensure intuitive interface and responsive interactions

### Quality Contribution
Testing contributes to overall application quality by:
- **Preventing Regressions:** Automated tests catch breaking changes early
- **Validating Requirements:** Each test ties directly to user story acceptance criteria
- **Ensuring Stability:** Integration tests verify external dependencies work correctly
- **Building Confidence:** Comprehensive coverage enables safe refactoring and feature additions

---

## 3) Testing Types and Levels

### Unit Testing
- **Purpose:** Test individual functions and methods in isolation
- **Scope:** Utils functions (email parsing, chess move extraction, FEN updates)
- **Tools:** Python unittest framework
- **Lifecycle Alignment:** Run during development before committing code

### Integration Testing
- **Purpose:** Verify interactions between components and external services
- **Scope:** Gmail API calls, IMAP/SMTP connections, database operations, Stockfish engine
- **Tools:** Integration test suite with mock Gmail responses
- **Lifecycle Alignment:** Run before pull request merge

### System Testing
- **Purpose:** Validate end-to-end workflows
- **Scope:** Complete user journeys (login → sync → view thread → make move → send email)
- **Tools:** Selenium for UI automation, API testing for endpoints
- **Lifecycle Alignment:** Run at end of sprint before release

### Acceptance Testing
- **Purpose:** Verify features meet user story acceptance criteria
- **Scope:** User-facing features against defined requirements
- **Tools:** Manual testing with test scenarios, user feedback sessions
- **Lifecycle Alignment:** Conducted during sprint review

---

## 4) Managing Tests

### Test Tracking System
We use a **Test Management Spreadsheet** with the following structure:

| Test ID | Test Name | Type | Related Requirement | Dependencies | Status | Result | Date | Notes |
|---------|-----------|------|---------------------|--------------|--------|--------|------|-------|
| TC-001 | Gmail OAuth Login | Integration | REQ-AUTH-001 | Google OAuth API | Active | Pass | 2025-11-21 | Token refreshed successfully |
| TC-002 | Incremental Email Sync | Integration | REQ-SYNC-003 | IMAP, User.last_sync | Active | Pass | 2025-11-21 | 95% faster sync |
| TC-003 | Chess Move Validation | Unit | REQ-CHESS-002 | Chess library | Active | Pass | 2025-11-20 | Validates UCI format |

### Relationship to Requirements
Each test case is mapped to specific requirements:
- **REQ-AUTH-001:** User authentication via Google OAuth
- **REQ-SYNC-003:** Incremental sync using timestamp-based filtering
- **REQ-CHESS-002:** Chess move validation and FEN updates

### Dependency Tracking
Dependencies are explicitly documented:
- **External Services:** Gmail API, Stockfish engine availability
- **Database State:** Requires specific User/Thread/Message records
- **Prerequisites:** Successful OAuth authentication before sync tests

### Outcome Recording
Test results include:
- **Pass/Fail Status:** Clear indication of test outcome
- **Execution Date:** Timestamp of last test run
- **Notes:** Details on failures, edge cases discovered, performance metrics
- **Screenshots/Logs:** Attached for failed tests to aid debugging

---

## 5) Testing Scope

### In Scope

**Core Features:**
- User authentication (Google OAuth)
- Email synchronization (fetch new threads, sync existing threads)
- Thread and message display
- Chess game state management (FEN tracking, move validation)
- Email composition and sending
- Attachment upload and download
- Message and thread deletion (local database only)
- Forward email functionality with attachments
- Custom labels management
- Incremental sync optimization

**Integration Points:**
- Gmail API (sending emails, fetching labels)
- IMAP/SMTP (email retrieval and sending)
- Stockfish chess engine (move evaluation)
- SQLite database operations

**Browsers/Platforms:**
- Chrome, Firefox, Edge (latest versions)
- Windows, macOS, Linux

### Out of Scope

**Excluded from Testing:**
- Mobile native apps (web-only focus)
- Internet Explorer or legacy browsers
- Gmail server-side functionality
- Third-party chess engine accuracy (assumed correct)
- Email delivery infrastructure beyond SMTP handoff

---

## 6) Test Environment

### Development Environment
- **OS:** Windows 11, macOS 13+, Ubuntu 22.04
- **Python Version:** 3.9+
- **Flask Version:** 2.x
- **Database:** SQLite (local development)
- **Browser:** Chrome/Firefox latest versions

### Testing Servers
- **Local Development Server:** Flask development server on localhost:5000
- **Staging Environment:** Deployment server with production-like configuration
- **Test Database:** Separate SQLite instance with test data

### Hardware Requirements
- **Minimum:** 4GB RAM, 2-core CPU
- **Recommended:** 8GB RAM, 4-core CPU for Stockfish evaluation

### Software Dependencies
- **Required Services:**
  - Gmail API credentials (OAuth 2.0 client ID/secret)
  - IMAP access enabled on test Gmail accounts
  - Stockfish chess engine installed locally
- **Python Packages:** Flask, SQLAlchemy, Authlib, python-chess, imaplib, smtplib, bleach, OpenAI SDK

### Test Accounts
- **Primary Test Account:** test.mailchess@gmail.com
- **Secondary Account:** opponent.mailchess@gmail.com
- **Purpose:** Simulate email exchanges between users

---

## 7) Test Data

### Data Sources

**Real Gmail Data (Development):**
- Actual email threads from test accounts
- Used for exploratory testing and manual validation

**Synthetic Test Data:**
- Generated email messages with known chess moves
- Predefined thread structures for edge case testing
- Sample attachments (PDF, PNG files)

### Data Preparation

**Database Seeding:**
```python
# Create test user
test_user = User(
    email='test.mailchess@gmail.com',
    google_id='test123',
    name='Test User',
    last_sync=datetime(2025, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
)

# Create test thread
test_thread = Thread(
    gmail_thread_id='thread123',
    subject='Chess Game with Opponent',
    fen='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
    user_id=test_user.id
)

# Create test message with chess move
test_message = Message(
    gmail_message_id='msg123',
    thread_id=test_thread.id,
    sender='opponent@example.com',
    recipient='test.mailchess@gmail.com',
    body_plain='Move: e2e4',
    move='e2e4',
    date=datetime.now(timezone.utc)
)
```

### Data Management
- **Isolation:** Each test suite uses separate database fixtures
- **Cleanup:** Database reset after each test run
- **Privacy:** No production user data in test environments
- **Version Control:** Test data fixtures stored in `tests/fixtures/`

---

## 8) Test Case Design

### Design Process
1. **Requirement Analysis:** Extract testable conditions from user stories
2. **Test Scenario Creation:** Define high-level scenarios covering acceptance criteria
3. **Test Case Specification:** Detail steps, inputs, and expected outcomes
4. **Peer Review:** Team reviews test cases for completeness

### Organization Structure
```
tests/
├── unit/
│   ├── test_email_utils.py
│   ├── test_chess_utils.py
│   └── test_gmail_api.py
├── integration/
│   ├── test_oauth_flow.py
│   ├── test_email_sync.py
│   └── test_send_email.py
├── system/
│   ├── test_user_journeys.py
│   └── test_end_to_end.py
└── fixtures/
    ├── sample_emails.json
    └── test_database.sql
```

### Prioritization
- **P0 (Critical):** Authentication, email sync, move validation
- **P1 (High):** Email sending, thread display, attachment handling
- **P2 (Medium):** Labels, deletion, forward functionality
- **P3 (Low):** UI polish, optional features

### Categorization
- **Functional:** Feature-specific tests
- **Non-Functional:** Performance, security, usability
- **Regression:** Tests for previously fixed bugs

---

## 9) Test Execution

### Detailed Test Case Examples

#### **Test Case 1: Gmail OAuth Authentication Flow**

**Test ID:** TC-AUTH-001
**Type:** Integration Test
**Priority:** P0 (Critical)
**Related Requirement:** REQ-AUTH-001 - Users must authenticate via Google OAuth
**Dependencies:**
- Google OAuth API available
- Valid client ID and secret configured
- Test Gmail account credentials

**Preconditions:**
- User is not logged in
- Flask application is running
- OAuth credentials are configured in environment variables

**Test Steps:**
1. Navigate to `http://localhost:5000/`
2. Click "Login with Google" button
3. Enter test account credentials on Google consent screen
4. Grant requested permissions (email, Gmail access)
5. Verify redirect to `/inbox` route
6. Check session contains `access_token` and `user` data

**Expected Outcomes:**
- User successfully redirected to inbox page
- Session contains valid OAuth access token
- User record created in database with `google_id`, `email`, `name`, `picture`
- Token can be used for Gmail API calls

**Actual Result:** ✅ Pass (2025-11-21)
**Notes:** Access token expires after 1 hour; refresh token mechanism tested separately.

---

#### **Test Case 2: Incremental Email Sync Performance**

**Test ID:** TC-SYNC-002
**Type:** Integration + Performance Test
**Priority:** P0 (Critical)
**Related Requirement:** REQ-SYNC-003 - Implement incremental sync for faster performance
**Dependencies:**
- User.last_sync timestamp field in database
- IMAP access to test Gmail account
- Test account has 100+ historical emails

**Preconditions:**
- User is authenticated
- User has `last_sync` timestamp set to 7 days ago
- Test Gmail account has 5 new emails since last sync
- 100 older emails exist before last sync date

**Test Steps:**
1. Record initial sync timestamp: `2025-11-14 12:00:00 UTC`
2. Trigger sync via POST `/api/sync-existing`
3. Monitor IMAP search query logs
4. Measure sync duration
5. Verify only new emails (after `last_sync`) are fetched
6. Check `User.last_sync` updated to current time

**Expected Outcomes:**
- IMAP query includes `SINCE 14-Nov-2025` filter
- Only 5 new emails processed (not all 105 emails)
- Sync completes in <5 seconds (vs 30+ seconds without incremental sync)
- `User.last_sync` updated to current UTC timestamp
- No duplicate messages created in database

**Actual Result:** ✅ Pass (2025-11-21)
**Performance Metrics:**
- Sync time: 3.2 seconds (95% improvement from baseline)
- IMAP search filtered to 5 emails as expected
- Database integrity maintained (no duplicates)

**Notes:** Significant performance improvement verified. First-time sync (no `last_sync`) still fetches all emails as expected.

---

#### **Test Case 3: Chess Move Extraction and FEN Update**

**Test ID:** TC-CHESS-003
**Type:** Unit Test
**Priority:** P0 (Critical)
**Related Requirement:** REQ-CHESS-002 - Extract chess moves from emails and update game state
**Dependencies:**
- `python-chess` library
- Email parsing utilities
- FEN validation functions

**Preconditions:**
- Thread exists with initial FEN: `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1`
- Test email message body contains "Move: e2e4"

**Test Steps:**
1. Parse email body: `"Hello! Here's my move:\nMove: e2e4\nYour turn!"`
2. Call `extract_chess_move(body)`
3. Verify extracted move is `'e2e4'`
4. Create chess board from thread FEN
5. Apply move using `board.push(chess.Move.from_uci('e2e4'))`
6. Verify new FEN: `rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1`
7. Test illegal move rejection: "Move: e2e5" (invalid)

**Expected Outcomes:**
- Valid move `e2e4` extracted correctly from plain text
- FEN updated accurately to reflect pawn advance
- Illegal move `e2e5` raises validation error
- Thread.fen field updated in database
- Move stored in Message.move field

**Actual Result:** ✅ Pass (2025-11-20)
**Edge Cases Tested:**
- Move with promotion: `e7e8q` ✅
- Castling: `e1g1` (kingside) ✅
- Case insensitivity: `E2E4` correctly parsed ✅
- Invalid format: `e2-e4` (not UCI) ❌ Failed - Added regex flexibility

**Notes:** Added support for common chess notation variations (e2-e4, e4, etc.) converted to UCI format.

---

### Defect Management

**Recording Defects:**
- Use GitHub Issues with template:
  - Title: `[BUG] Brief description`
  - Labels: `bug`, `priority:high/medium/low`
  - Description: Steps to reproduce, expected vs actual, screenshots

**Tracking Workflow:**
1. **New:** Defect reported
2. **Triaged:** Severity and priority assigned
3. **In Progress:** Developer working on fix
4. **Fixed:** Code merged, awaiting verification
5. **Verified:** Tester confirms fix
6. **Closed:** Issue resolved

**Example Defect:**
```
Issue #42: [BUG] Forward email fails with undefined subject

Priority: High
Type: Bug
Related Test: TC-FORWARD-005

Description:
When forwarding an email with no subject, JavaScript error occurs:
"Cannot read properties of undefined (reading 'startsWith')"

Steps to Reproduce:
1. Open thread with message lacking subject
2. Click forward button
3. Observe console error

Expected: Forward modal opens with subject "No subject"
Actual: Error thrown, modal doesn't open

Fix: Added null checks in forwardMessage() function (mail.py:952-976)
Status: Verified ✅
```

---

## 10) Automation Strategy

### Automated Test Cases

**Unit Tests (100% Automated):**
- Email parsing functions (`extract_chess_move`, `clean_message_body`)
- Chess utilities (`update_thread_fen`, `get_position_evaluation`)
- Helper functions (`extract_email_address`, `sanitize_html`)

**Integration Tests (80% Automated):**
- OAuth token refresh
- Database CRUD operations
- IMAP email fetching (mocked Gmail responses)

**Why Automate:**
- **Regression Detection:** Quickly catch breaking changes
- **Consistency:** Eliminate human error in repetitive tests
- **Efficiency:** Run hundreds of tests in seconds
- **CI/CD Integration:** Enable automated deployment pipelines

### Manual Test Cases

**Exploratory Testing:**
- UI/UX flow discovery
- Edge case scenarios not covered by automation
- Real Gmail API behavior under various network conditions

**Acceptance Testing:**
- User story validation with stakeholders
- Visual design verification

### Testing Tools and Frameworks

**Unit Testing:**
- **Framework:** Python `unittest`
- **Assertions:** Built-in assertion methods
- **Mocking:** `unittest.mock` for external dependencies

**Integration Testing:**
- **HTTP Client:** `requests` library for API testing
- **Database:** SQLite in-memory database for isolation
- **Mocking:** `responses` library for mocking Gmail API calls

**System Testing:**
- **UI Automation:** Selenium WebDriver
- **Browser:** Chrome in headless mode for CI
- **Assertions:** Selenium element presence and text validation

**Example Automated Test:**
```python
import unittest
from utils.email_utils import extract_chess_move

class TestChessMoveExtraction(unittest.TestCase):
    def test_extract_valid_move(self):
        """TC-CHESS-003: Extract valid UCI move from email body"""
        body = "Hello! Here's my move:\nMove: e2e4\nYour turn!"
        move = extract_chess_move(body)
        self.assertEqual(move, 'e2e4')

    def test_extract_no_move(self):
        """Verify None returned when no move present"""
        body = "Just saying hello, no move yet."
        move = extract_chess_move(body)
        self.assertIsNone(move)

    def test_case_insensitive(self):
        """Verify move extraction is case-insensitive"""
        body = "Move: E2E4"
        move = extract_chess_move(body)
        self.assertEqual(move, 'e2e4')

if __name__ == '__main__':
    unittest.main()
```

---

## 11) Performance and Load Testing

### Performance Testing Strategy

**Metrics to Measure:**
1. **Email Sync Time:**
   - Baseline (all emails): 30+ seconds for 100 emails
   - Optimized (incremental): <5 seconds for 5 new emails
   - Target: 95% reduction in sync time

2. **Page Load Time:**
   - Inbox page: <2 seconds for 50 threads
   - Thread view: <1.5 seconds for 20 messages
   - Target: All pages load under 3 seconds

3. **Database Query Performance:**
   - Thread list query: <100ms
   - Message retrieval: <50ms per thread
   - Target: All queries under 200ms

### Load Testing Scenarios

**Scenario 1: Concurrent Users**
- Simulate 10 users simultaneously syncing emails
- Measure server response times and database connection pool
- Expected: No timeouts, all requests complete within 10 seconds

**Scenario 2: Large Thread Volume**
- Test inbox with 500+ threads
- Verify pagination and lazy loading performance
- Expected: Smooth scrolling, no browser freeze

**Scenario 3: Large Attachments**
- Upload and download 10MB PDF files
- Measure upload/download times
- Expected: Complete within 30 seconds on standard connection

### Tools
- **Backend:** Python `timeit` module for function timing
- **Frontend:** Chrome DevTools Performance profiler
- **Load Testing:** `locust` for simulating concurrent users

**Example Performance Test:**
```python
import time
from utils.email_utils import fetch_new_threads

def test_incremental_sync_performance():
    """TC-PERF-001: Verify incremental sync speed"""
    user_id = 1
    last_sync = datetime(2025, 11, 14, 12, 0, 0, tzinfo=timezone.utc)

    start_time = time.time()
    stats = fetch_new_threads(user_id, email, token, count=5, last_sync=last_sync)
    duration = time.time() - start_time

    assert duration < 5.0, f"Sync took {duration}s, expected <5s"
    assert stats['threads_fetched'] == 5
    print(f"✅ Incremental sync completed in {duration:.2f}s")
```

---

## 12) Security Testing

### Security Testing Areas

#### 1. Authentication and Authorization
**Tests:**
- Verify OAuth token is stored securely in session (not exposed in URLs)
- Test session expiration and token refresh mechanisms
- Confirm users can only access their own threads/messages
- Validate logout clears all session data

**Tools:** Manual inspection, Burp Suite for session analysis

#### 2. Input Validation
**Tests:**
- SQL injection attempts in search fields
- XSS attacks in email body rendering
- Path traversal in file upload/download
- CSRF token validation on state-changing requests

**Example:**
```python
def test_xss_prevention():
    """TC-SEC-001: Verify HTML sanitization prevents XSS"""
    malicious_html = '<script>alert("XSS")</script><p>Hello</p>'
    sanitized = sanitize_html(malicious_html)
    assert '<script>' not in sanitized
    assert '<p>Hello</p>' in sanitized  # Allowed tag preserved
```

#### 3. Data Protection
**Tests:**
- Email content not logged in plain text
- Database passwords encrypted
- OAuth secrets in environment variables (not code)
- File uploads validated for type and size

#### 4. API Security
**Tests:**
- Endpoints require valid session before access
- Rate limiting on sync operations (prevent abuse)
- Gmail API quota limits respected

### Vulnerability Scanning
- **Tool:** OWASP ZAP for automated vulnerability scanning
- **Frequency:** Weekly scans on staging environment
- **Remediation:** Critical vulnerabilities fixed within 48 hours

---

## 13) Usability and Accessibility Testing

### Usability Testing

**Scenarios:**
1. **First-Time User:** Can user log in and understand inbox within 2 minutes?
2. **Make Chess Move:** Can user find, view thread, and send move within 3 minutes?
3. **Error Recovery:** Can user understand and recover from sync errors?

**Metrics:**
- **Task Success Rate:** >90% users complete tasks without assistance
- **Time on Task:** Within expected time bounds
- **Error Rate:** <5% user errors per session

**Method:**
- 5-user testing sessions with think-aloud protocol
- Observe pain points and confusion areas
- Iterate UI based on feedback

### Accessibility Testing

**WCAG 2.1 Compliance:**
- **Level A (Minimum):** Must meet
- **Level AA (Recommended):** Target compliance

**Tests:**
1. **Keyboard Navigation:**
   - All features accessible via keyboard only
   - Tab order logical
   - Focus indicators visible

2. **Screen Reader Compatibility:**
   - Test with NVDA/JAWS
   - Alt text on images
   - ARIA labels on interactive elements

3. **Color Contrast:**
   - Text meets 4.5:1 contrast ratio
   - UI elements meet 3:1 ratio

4. **Responsive Design:**
   - Usable at 200% zoom
   - Mobile-friendly (though not primary focus)

**Tools:**
- **Automated:** axe DevTools Chrome extension
- **Manual:** Keyboard-only navigation testing, screen reader testing

---

## 14) Regression Testing

### Purpose
Ensure new features or bug fixes don't break existing functionality.

### Strategy

**Automated Regression Suite:**
- Run full test suite (unit + integration) on every pull request
- CI/CD pipeline blocks merge if tests fail
- Tests cover all P0 and P1 features

**Regression Test Selection:**
- **Full Suite:** Run nightly on main branch
- **Smoke Tests:** Quick subset (<5 min) on every commit
- **Targeted Tests:** Related tests for specific feature changes

**Example Regression Scenario:**
```
Change: Added incremental sync feature (User.last_sync field)

Regression Tests to Run:
✅ TC-AUTH-001: OAuth flow still works
✅ TC-SYNC-001: Fetch new threads (without last_sync) works
✅ TC-SYNC-002: Incremental sync (with last_sync) works
✅ TC-DB-001: Database migrations applied correctly
✅ TC-THREAD-001: Thread display unchanged
```

### Regression Defect Tracking
- All regression bugs tagged with `regression` label
- Root cause analysis: Why didn't existing tests catch it?
- Add new test to prevent future recurrence

---

## 15) Testing Schedule

### Sprint-Based Timeline (2-week sprints)

**Week 1: Development + Unit Testing**
- Day 1-3: Feature development, write unit tests alongside code
- Day 4-5: Integration test development
- Deliverable: Feature implemented with >80% unit test coverage

**Week 2: Integration + System Testing**
- Day 6-7: Run integration tests, fix failures
- Day 8-9: System testing, end-to-end scenarios
- Day 10: Acceptance testing with stakeholders
- Deliverable: Feature ready for release

**Continuous Activities:**
- Automated tests run on every commit (CI/CD)
- Daily smoke tests on development branch
- Weekly regression test suite on main branch

### Milestones

| Milestone | Testing Phase | Completion Criteria |
|-----------|---------------|---------------------|
| Sprint 1 | Auth + Sync | OAuth and email sync tested, >85% coverage |
| Sprint 2 | Chess Features | Move validation and FEN updates tested |
| Sprint 3 | Email Actions | Send, forward, delete thoroughly tested |
| Sprint 4 | Performance | Incremental sync performance validated |
| Release | Full Regression | All P0/P1 tests passing, no critical bugs |

---

## 16) Roles and Responsibilities

### Team Structure

**Development Team (2-3 developers):**
- Write unit tests for their code
- Fix bugs found during testing
- Participate in code reviews including test coverage
- Maintain test fixtures and data

**Quality Assurance Lead (1 person):**
- Design integration and system test cases
- Maintain test plan documentation
- Coordinate testing activities across sprints
- Report test metrics and coverage

**Product Owner:**
- Define acceptance criteria for user stories
- Participate in acceptance testing
- Prioritize bug fixes vs new features

**DevOps Engineer:**
- Set up CI/CD pipeline for automated testing
- Maintain test environments
- Monitor test execution performance

### RACI Matrix

| Activity | Developer | QA Lead | Product Owner | DevOps |
|----------|-----------|---------|---------------|---------|
| Write unit tests | R, A | C | I | I |
| Design integration tests | C | R, A | C | I |
| Execute manual tests | C | R, A | C | - |
| Set up CI/CD | C | I | - | R, A |
| Review test results | C | R, A | I | C |
| Prioritize bug fixes | I | C | R, A | I |

**Legend:** R = Responsible, A = Accountable, C = Consulted, I = Informed

---

## 17) Exit Criteria

### Unit Testing Phase
- [ ] All unit tests passing (0 failures)
- [ ] Code coverage ≥80% for new code
- [ ] All functions have corresponding test cases
- [ ] No high-priority bugs remaining

### Integration Testing Phase
- [ ] All integration tests passing
- [ ] External service integrations verified (Gmail API, IMAP, Stockfish)
- [ ] Database operations validated
- [ ] No critical bugs, <3 high-priority bugs

### System Testing Phase
- [ ] All end-to-end scenarios passing
- [ ] Performance benchmarks met (incremental sync <5s)
- [ ] Security vulnerabilities addressed
- [ ] Usability issues resolved

### Acceptance Testing Phase
- [ ] All user story acceptance criteria met
- [ ] Product owner sign-off received
- [ ] No critical or high bugs in production candidate
- [ ] Documentation updated (user guide, API docs)

### Release Readiness
- [ ] Full regression suite passes
- [ ] Performance metrics within acceptable range
- [ ] Security scan shows no critical vulnerabilities
- [ ] Backup and rollback plan in place

---

## 18) Reporting and Communication

### Test Reports

**Daily Standup Report:**
- Tests executed today
- Pass/fail summary
- Blockers or issues

**Sprint Review Report:**
- Total tests: 247
- Passing: 242 (98%)
- Failing: 3 (1.2%)
- Skipped: 2 (0.8%)
- New tests added: 15
- Code coverage: 84%
- Critical bugs: 0
- High priority bugs: 2

**Example Dashboard:**
```
MailChess Test Dashboard - Sprint 4
=====================================
Last Updated: 2025-11-21 14:30 UTC

Test Execution Summary:
✅ Unit Tests:        145/147 (99%)
✅ Integration Tests: 82/85  (96%)
✅ System Tests:      15/15  (100%)
⚠️  Total:            242/247 (98%)

Code Coverage: 84% (Target: 80%)

Failed Tests:
❌ TC-SYNC-004: IMAP timeout on large mailbox
❌ TC-LABEL-002: Custom label icon upload size validation
❌ TC-PERF-003: Stockfish evaluation timeout on complex position

Bugs by Priority:
🔴 Critical: 0
🟠 High: 2
🟡 Medium: 5
🟢 Low: 8

Next Steps:
- Fix IMAP timeout (increase timeout to 120s)
- Add file size validation before upload
- Implement Stockfish timeout handling
```

### Communication Channels

**Frequency:**
- **Daily:** Slack notification of CI/CD test results
- **Weekly:** Test summary email to team
- **Sprint End:** Comprehensive report in sprint review

**Format:**
- **Automated:** CI/CD sends GitHub PR comment with test results
- **Manual:** Test summary in Google Sheets, shared with stakeholders
- **Metrics:** Grafana dashboard showing test trends over time

### Stakeholder Communication
- Product Owner: Weekly test summary, focus on acceptance criteria
- Development Team: Immediate Slack notification on test failures
- Management: Monthly quality metrics report (coverage, bug trends)

---

## Review and Revision

### Document Maintenance

**Review Cycle:**
- **Sprint Start:** Review test plan for upcoming features
- **Sprint Retrospective:** Discuss what worked, what needs improvement
- **Quarterly:** Comprehensive review and update

**Revision Process:**
1. Gather feedback from team (developers, QA, product owner)
2. Identify gaps in testing coverage or outdated sections
3. Propose changes in pull request for review
4. Update document version number and date
5. Communicate changes to all stakeholders

**Triggers for Revision:**
- New feature requiring different testing approach
- Tool or framework changes
- Process improvements identified in retrospectives
- Regulatory or compliance requirement changes

**Version Control:**
- Document stored in Git repository (`docs/testing_plan.md`)
- Each revision tagged with version number
- Change log maintained in document header

---

## Appendix

### Test Case Template
```markdown
**Test ID:** TC-XXX-###
**Type:** Unit/Integration/System/Acceptance
**Priority:** P0/P1/P2/P3
**Related Requirement:** REQ-XXX-###
**Dependencies:** [List dependencies]

**Preconditions:**
[State required before test]

**Test Steps:**
1. Step 1
2. Step 2
3. Step 3

**Expected Outcomes:**
- Outcome 1
- Outcome 2

**Actual Result:** Pass/Fail
**Notes:** [Additional observations]
```

### Useful Commands

**Run All Tests:**
```bash
python -m unittest discover -s tests -p 'test_*.py'
```

**Run Specific Test File:**
```bash
python -m unittest tests.unit.test_email_utils
```

**Run with Coverage:**
```bash
coverage run -m unittest discover
coverage report
coverage html  # Generate HTML report
```

**Run CI/CD Pipeline Locally:**
```bash
pytest tests/ --cov=. --cov-report=html
```

---

**Document Version:** 1.0
**Last Updated:** November 21, 2025
**Next Review Date:** December 21, 2025
**Owner:** QA Lead
