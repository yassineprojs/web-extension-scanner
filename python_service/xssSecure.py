import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin,urlparse,parse_qs
import json

class XSSSecurityAnalyzer:
    def __init__(self, url):
        self.session = requests.Session()
        self.findings = []
        self.vulnerabilities = []
        self.visited_urls = set()
        self.score = 0

    async def analyze(self, url, content):
        self.url = url
        self.check_headers(self.session.headers)
        self.analyze_content(content)
        self.check_forms(content)
        await self.check_reflected_xss(url, content)
        return self.generate_report()
    
    # checking for header:
    def check_headers(self, headers):
        self._check_content_security_policy(headers)
        self._check_strict_transport_security(headers)
        self._check_x_frame_options(headers)
        self._check_x_content_type_options(headers)
        self._check_referrer_policy(headers)
        self._check_feature_policy(headers)

    # prevent xss attacks
    def _check_content_security_policy(self, headers):
        csp = headers.get('Content-Security-Policy')
        if csp:
            self.score += 1
            self.findings.append("CSP header present - good")
            self._analyze_csp(csp)
        else:
            self.findings.append("CSP header missing - consider implementing")

    def _analyze_csp(self, csp):
        directives = csp.split(';')
        for directive in directives:
            directive = directive.strip()
            if directive.startswith('default-src'):
                if "'none'" in directive:
                    self.score += 1
                    self.findings.append("CSP uses 'default-src: none' - strict policy")
                elif "'self'" in directive:
                    self.score += 0.5
                    self.findings.append("CSP uses 'default-src: self' - moderately strict")
            elif directive.startswith('script-src'):
                if "'unsafe-inline'" in directive or "'unsafe-eval'" in directive:
                    self.findings.append("CSP allows unsafe scripts - consider removing 'unsafe-inline' and 'unsafe-eval'")
                else:
                    self.score += 1
                    self.findings.append("CSP properly restricts script sources")


    # tells browsers to only connect to the server over HTTPS, helping to prevent man-in-the-middle attacks.
    def _check_strict_transport_security(self, headers):
        hsts = headers.get('Strict-Transport-Security')
        if hsts:
            self.score += 1
            self.findings.append("HSTS header present - good")
            if 'includeSubDomains' in hsts:
                self.score += 0.5
                self.findings.append("HSTS includes subdomains")
            if 'preload' in hsts:
                self.score += 0.5
                self.findings.append("HSTS preload ready")
            max_age = re.search(r'max-age=(\d+)', hsts)
            if max_age:
                age = int(max_age.group(1))
                if age >= 31536000:
                    self.score += 0.5
                    self.findings.append("HSTS max-age is at least one year")
                else:
                    self.findings.append(f"HSTS max-age is {age} seconds - consider increasing to at least one year")
        else:
            self.findings.append("HSTS header missing - consider implementing")

    # protect against clickjacking attacks
    def _check_x_frame_options(self, headers):
        x_frame_options = headers.get('X-Frame-Options')
        if x_frame_options:
            self.score += 1
            self.findings.append(f"X-Frame-Options header present: {x_frame_options}")
            if x_frame_options.upper() in ['DENY', 'SAMEORIGIN']:
                self.score += 0.5
                self.findings.append("X-Frame-Options properly set to prevent clickjacking")
        else:
            self.findings.append("X-Frame-Options header missing - consider implementing to prevent clickjacking")

    # prevent browsers from MIME-sniffing a response away from the declared content-type
    def _check_x_content_type_options(self, headers):
        x_content_type_options = headers.get('X-Content-Type-Options')
        if x_content_type_options:
            if x_content_type_options.lower() == 'nosniff':
                self.score += 1
                self.findings.append("X-Content-Type-Options header properly set to 'nosniff'")
            else:
                self.findings.append(f"X-Content-Type-Options header present but not set to 'nosniff': {x_content_type_options}")
        else:
            self.findings.append("X-Content-Type-Options header missing - consider implementing to prevent MIME type sniffing")

    # controls how much referrer information is included with requests, helping to reduce leakage of browsing information.
    def _check_referrer_policy(self, headers):
        referrer_policy = headers.get('Referrer-Policy')
        if referrer_policy:
            self.score += 1
            self.findings.append(f"Referrer-Policy header present: {referrer_policy}")
            if referrer_policy.lower() in ['no-referrer', 'strict-origin-when-cross-origin']:
                self.score += 0.5
                self.findings.append("Referrer-Policy set to a strict value")
        else:
            self.findings.append("Referrer-Policy header missing - consider implementing to control referrer information")

    # allows a site to control which features and APIs can be used in the browser
    def _check_feature_policy(self, headers):
        feature_policy = headers.get('Feature-Policy') or headers.get('Permissions-Policy')
        if feature_policy:
            self.score += 1
            self.findings.append("Feature-Policy/Permissions-Policy header present - good")
            # Add more detailed analysis of Feature-Policy directives if needed
        else:
            self.findings.append("Feature-Policy/Permissions-Policy header missing - consider implementing to control browser features")


    def analyze_content(self, content):
        soup = BeautifulSoup(content, 'html.parser')

        # Check for inline scripts
        inline_scripts = soup.find_all('script', src=False)
        if inline_scripts:
            self.findings.append(f"Inline scripts detected ({len(inline_scripts)}) - consider moving to external files")
            self.score -= len(inline_scripts)

        # Check for unsafe JavaScript practices
        unsafe_js_patterns = {
            r'document\.write': "Usage of document.write detected - potential XSS risk",
            r'eval\s*\(': "Usage of eval() detected - potential security risk",
            r'innerHTML\s*=': "Direct manipulation of innerHTML detected - potential XSS risk",
            r'on\w+\s*=': "Inline event handlers detected - consider using addEventListener",
            r'setTimeout\s*\(\s*[\'"`]': "Potentially unsafe use of setTimeout with string argument",
            r'setInterval\s*\(\s*[\'"`]': "Potentially unsafe use of setInterval with string argument",
        }

        for pattern, message in unsafe_js_patterns.items():
            if re.search(pattern, content, re.IGNORECASE):
                self.findings.append(message)
                self.score -= 1

        # Check for proper output encoding
        if re.search(r"<[^>]*>.*&lt;script&gt;", content):
            self.score += 1
            self.findings.append("Evidence of HTML encoding in output - good practice")

    async def check_reflected_xss(self, url, content):
        payloads = self.generate_payloads()
        
        # Check URL parameters
        parsed_url = urlparse(url)
        params = parse_qs(parsed_url.query)
        for param, values in params.items():
            for payload in payloads:
                test_url = url.replace(f"{param}={values[0]}", f"{param}={payload}")
                async with self.session.get(test_url) as response:
                    response_text = await response.text()
                    if payload in response_text:
                        self.vulnerabilities.append(f"Reflected XSS found in URL parameter {param} at {url}")

        # Check form inputs
        soup = BeautifulSoup(content, "html.parser")
        forms = soup.find_all("form")
        for form in forms:
            await self.check_form_xss(url, form, payloads)
        
    def check_form_xss(self,url,form,payloads):
        action = urljoin(url,form.get("action",''))
        method = form.get('method','get').lower()
        for payload in payloads:
            data = {input.get('name'): payload for input in form.find_all('input') if input.get('name')}
            if method == 'post':
                with self.session.post(action,data=data) as response:
                    response_text =  response.text()
            else:
                with self.session.get(action, params = data)as response:
                    response_text =  response.text()
        if payload in response_text:
            self.vulnerabilities.append(f"Reflected XSS ound in form at {url}")
            return 
 
    def check_forms(self, content):
        soup = BeautifulSoup(content, 'html.parser')
        forms = soup.find_all('form')

        for form in forms:
            if not form.find('input', attrs={'type': 'hidden', 'name': re.compile(r'csrf', re.I)}):
                self.findings.append(f"Form {form.get('id', 'unknown')} lacks CSRF token - potential XSS risk")

    def generate_report(self):
        overall_assessment = "Weak XSS protection - improvements recommended"
        if self.score >= 2:
            overall_assessment = "Good XSS protection measures in place"
        elif self.score == 1:
            overall_assessment = "Some XSS protection, but improvements needed"

        self.vulnerabilities.append({
            "url": self.url,
            "score": self.score,
            "findings": self.findings,
            "overall_assessment": overall_assessment
        })

    def generate_payloads(self):
        return [
            "<script>alert('XSS')</script>",
            "javascript:alert('XSS')",
            "<img src=x onerror=alert('XSS')>",
            "<svg onload=alert('XSS')>",
            "'-alert('XSS')-'"
        ]
