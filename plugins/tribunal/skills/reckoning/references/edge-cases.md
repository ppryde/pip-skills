# Edge cases: API errors and rate limits

Read this only when a call fails or is rate limited.

- **REST rate limiting**: `gh` uses authenticated requests (5000 requests/hour)
- **GraphQL rate limiting**: Separate from REST (5000 points/hour, variable cost per query). If a GraphQL query returns a rate limit error (`RATE_LIMITED`), inform the user and offer two options: (1) proceed without thread resolution status (all comments treated as potentially unresolved), or (2) wait and retry. If rate limiting occurs mid-pagination (some pages fetched, some not), inform the user that thread resolution data is partial and mark any comments whose threads were not checked as "resolution status unknown" rather than defaulting to unresolved. Do not silently skip the GraphQL data
- **API errors**: If any `gh api` call (REST or GraphQL) returns an HTTP error, malformed JSON, or network timeout, inform the user which API call failed and what data will be missing. Offer to retry or continue without that data source (e.g., proceed without thread resolution if GraphQL fails). Do not silently skip failed API calls.
