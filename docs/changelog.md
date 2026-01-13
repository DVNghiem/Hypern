# Changelog

All notable changes to Hypern will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.15] - 2024-01-15

### Added
- Enhanced response builder API with fluent interface
- Improved type hints for better IDE support
- Documentation generation support

### Changed
- Updated dependencies to latest stable versions
- Performance optimizations in request routing

### Fixed
- Minor bug fixes in request handling
- Memory leak fixes in long-running processes

## [0.3.x] - Previous Releases

### Added
- Core Rust runtime implementation
- Python bindings via PyO3
- Multi-process architecture support
- Async/await support
- Request and Response objects
- Router and Route management
- Built-in middleware support
- WebSocket support
- Background task scheduling
- File upload handling

### Performance
- Optimized memory allocation with jemalloc/mimalloc
- Fast JSON serialization with orjson
- Binary serialization with msgpack
- High-performance event loop with uvloop (on supported platforms)

### Security
- CORS configuration support
- Rate limiting capabilities
- Request validation framework

## [Unreleased]

### Planned Features
- Built-in authentication/authorization system
- Enhanced OpenAPI/Swagger documentation
- GraphQL support
- Streaming response support
- Server-Sent Events (SSE)
- HTTP/2 support enhancements
- Improved monitoring and metrics
- Plugin system for extensions

### Under Consideration
- Database integration helpers
- ORM support
- Template engine integration
- Session management
- Caching layer
- Message queue integration

## Version History

### Version 0.3.x Series
Focus on stability and performance improvements

### Version 0.2.x Series
Initial public release with core features

### Version 0.1.x Series
Alpha releases and early development

## Migration Guides

### Migrating to 0.3.x

No breaking changes from 0.2.x. All existing code should work without modifications.

### Future Breaking Changes

We aim to maintain backward compatibility but may introduce breaking changes in major version updates (1.0.0, 2.0.0, etc.). All breaking changes will be clearly documented with migration guides.

## Contributing

We welcome contributions! Please see our [Contributing Guide](contributing/guidelines.md) for details on how to submit changes and our development process.

## Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/DVNghiem/hypern/issues)
- **Documentation**: [Read the full documentation](https://hypern.dev)
- **Community**: Join our community discussions

## License

Hypern is released under the MIT License. See [LICENSE](https://github.com/DVNghiem/hypern/blob/main/LICENSE) for details.
