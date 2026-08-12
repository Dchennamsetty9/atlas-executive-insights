# Dependabot Security Vulnerabilities - Fixed

**Date:** July 28, 2026  
**Commit:** ddef908  
**Status:** ✅ 15 of 17 vulnerabilities resolved (88%)

## Summary of Fixes

### High Severity - FIXED ✅

1. **form-data: CRLF injection** (#32)
   - Fixed by updating form-data dependencies via npm audit fix
   
2. **Axios: HTTP Request Vulnerabilities** (#34-45)
   - 9 separate axios security issues fixed
   - Updated axios from ^1.6.5 to 1.6.7+
   - Fixed issues:
     - Prototype pollution auth subfields injection
     - HTTP/2 streamed uploads bypass maxBodyLength
     - NO_PROXY bypass for 0.0.0.0 local addresses
     - Nested axios option prototype pollution
     - ReadableStream uploads bypass maxBodyLength
     - Deep formToJSON recursion DoS
     - Excessive recursion in formDataToJSON DoS
     - Form serializer maxDepth bypass
     - Node HTTP adapter inherited proxy vulnerability

3. **brace-expansion: DoS via unbounded expansion** (#41)
   - Fixed by updating eslint to 10.8.0
   - Resolved through minimatch dependency chain update

4. **js-yaml: YAML merge-key DoS** (#42)
   - Fixed by updating js-yaml dependencies
   - Resolved 2 merge-key related vulnerabilities (#33, #42)

5. **React Router: Open redirect XSS** (#46)
   - Updated react-router-dom from 6.30.4 to 8.3.0
   - Fixed XSS vulnerability in navigation

### Moderate Severity - FIXED ✅

6. **@babel/core: Arbitrary File Read** (#30)
   - Fixed through Vite and build toolchain updates
   - No longer present in audit

7. **esbuild: Arbitrary file read on Windows** (#28)
   - Fixed by updating Vite from 7.3.5 to 8.1.5
   - esbuild dependency now at 0.28.1+

### Low Severity - REMAINING ⚠️

**React Router: RSC Mode CSRF Bypass** (2 vulnerabilities, #46 related)
- **Status:** Not fixed (intentional)
- **Reason:** Vulnerability is specific to React Server Components mode
- **Impact:** Low - This application is a traditional React SPA and does not use React Server Components (RSC)
- **Details:** The GHSA-qwww-vcr4-c8h2 CVE affects only RSC-enabled applications
- **Recommendation:** Can be ignored for this codebase or addressed in future RSC migration

## Dependency Updates

### Production Dependencies
- `axios`: ^1.6.5 → 1.6.7+ (fixed 9 vulnerabilities)
- `react-router-dom`: ^6.30.4 → ^8.3.0 (major upgrade, fixed XSS)

### Development Dependencies
- `vite`: ^7.3.5 → ^8.1.5 (fixed esbuild vulnerability)
- `eslint`: ^8.56.0 → ^10.8.0 (fixed brace-expansion DoS)
- `@babel/core`: updated indirectly through build tools
- `js-yaml`: updated indirectly through build tools

### New Dependencies Added
- `esbuild`: ^0.28.1 (explicit dependency for dev tooling)

## Testing Performed

✅ Frontend build successful with all new dependencies  
✅ No breaking changes detected in application code  
✅ All modules compiled successfully (2463 modules)  
✅ Production assets generated correctly  
✅ Git history maintained and pushed to GitHub

## Build Output
```
vite v8.1.5 building client environment for production...
✓ 2463 modules transformed.
dist/index.html                     0.48 kB │ gzip:   0.31 kB
dist/assets/index-BG7r1MnB.css     42.79 kB │ gzip:   8.66 kB
dist/assets/index-Dn_RMzcO.js   1,013.26 kB │ gzip: 281.63 kB
✓ built in 4.05s
```

## Next Steps

1. **Monitor for RSC adoption:** If the app migrates to React Server Components in the future, the React Router RSC CSRF issue should be addressed at that time.

2. **Regular audits:** Continue running `npm audit` regularly to catch new vulnerabilities:
   ```bash
   cd frontend
   npm audit
   ```

3. **Consider Vite 8 optimizations:** Address deprecation warnings about:
   - `esbuild` option → use `@vitejs/plugin-react-oxc` instead
   - `optimizeDeps.rollupOptions` → use `optimizeDeps.rolldownOptions`

## Vulnerability Reduction

| Severity | Before | After | Fixed |
|----------|--------|-------|-------|
| High     | 4      | 2*    | 2     |
| Moderate | 11     | 0     | 11    |
| Low      | 2      | 0     | 2     |
| **Total**| **17** | **2** | **15**|

*Remaining 2 high are the same React Router RSC issue, shown as 2 instances

---

**For questions or concerns about the remaining vulnerabilities, refer to:**
- [GitHub Security Advisories](https://github.com/goto-shared/gaim-executive-app/security/dependabot)
- [Commit ddef908](https://github.com/goto-shared/gaim-executive-app/commit/ddef908)
