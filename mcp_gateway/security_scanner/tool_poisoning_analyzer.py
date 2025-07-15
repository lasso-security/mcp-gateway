import logging
import re
from typing import Dict, List, Any
from mcp_gateway.security_scanner.config import logger

class ToolAnalyzer:
    """
    Analyzes MCP tool descriptions to detect hidden instructions, sensitive files,
    and sensitive actions.
    
    This class provides methods to identify potential security risks in tool
    descriptions by analyzing their content against predefined patterns.
    """
    
    def __init__(self):
        """
        Initialize the ToolAnalyzer with predefined patterns for detecting
        sensitive content in tool descriptions.
        """
        # Patterns for hidden instructions
        self.hidden_instruction_patterns: List[str] = [
            r"(ignore|disregard) (earlier|previous|prior) (instructions|constraints)",
            r"bypass (security|restrictions|limitations)",
            r"\b(don't|do not) (tell|inform|alert|notify|mention)\s+(anyone|the user|them|others|somebody)",
            r"(keep|maintain) (this|these) (secret|hidden)",
            r"(this is between us|our secret)",
            r"(deleted|ignore|skip) this (after|once) reading",
            r"(silently|secretly) (execute|perform|run|do|implement)",
            r"instructions? (are|is) confidential",
            r"this (will be|is) our (little|private) secret",
            r"following instructions? (should|must) be (hidden|concealed|obscured)",
            r"(pretend|act) (like|as if) (you (are|were) just|you're just)",
            r"don't (make (it|this)|let (it|this) be) (obvious|apparent|evident|clear|noticeable)",
            r"(without|don't) (alerting|informing|notifying) (the|any|other) (user|person|people|individuals)",
            r"(this|that|it|these|those) (is|are) (confidential|secret|private|sensitive)",
        ]
        
        # Sensitive file patterns
        self.sensitive_file_patterns: List[str] = [
            r"\.env",
            r"(?:config(?:_|\.)secrets?)\.(?:json|yaml|yml|xml|txt|properties)",
            r"\.pem$",
            r"\.key$",
            r"(?:password|credentials)\.(?:txt|json|yaml|yml|xml)",
            r"(?:ssh|private)(?:_|\.)key",
            r"\.htpasswd",
            r"id_rsa",
            r"\.aws/",
            r"\.ssh/",
            r"token\.(?:json|yaml|yml|xml|txt|properties)",
            r"api[_\-\.]?key",
            r"auth(?:entication)?[_\-\.]?(?:token|key)",
            r"oauth[_\-\.]?(?:token|key)",
            r"/etc/(?:passwd|hosts|sudoers|shadow)",
            r"(?:certificate|cert)[_\-\.]?(?:store|file)",
            r"keystore\.(?:jks|p12|pkcs12)",
        ]
        
        # Sensitive action patterns
        self.sensitive_action_patterns: List[str] = [
            r"(execute|run|spawn|create|invoke) (shell|bash|powershell|cmd|command)+",
            r"(chmod|chown) (\+|\-)(r|w|x|rw|rx|wx|rwx|[0-7]{3,4})",
            r"(delete|remove|drop) (database|table|collection|index)",
            r"(exec\(|eval\(|subprocess\.|\bos\.system\(|\bos\.popen\(|\bshell=True\b|\bexecfile\(|\bexecute_script\(|\.exec\(|javascript:|\bRuntime\.exec\(|\bProcess\.start\(|\beval\s*\(|\bnew\s+Function\(|\bDangerouslySetInnerHTML)",
            r"(connect|access) (external|remote) (server|api|service|host)",
            r"(encrypt|decrypt) (data|file|content)",
            r"(establish|create|open) (socket|connection|tunnel)", 
            r"(modify|change|update) (system|os|kernel) (settings|configuration)",
            r"(fetch|download) (from|at) (url|http|https)",
            r"(overwrite|truncate) (file|content)",
            r"network[_\-\s]?(scan|discovery|reconnaissance)",
            r"(port|vulnerability)[_\-\s]?scan",
            r"(install|inject)[_\-\s]?(rootkit|malware|backdoor)",
            r"(disable|bypass)[_\-\s]?(firewall|antivirus|security)",
            r"privilege[_\-\s]?escalation",
            r"data[_\-\s]?(exfiltration|theft)",
            r"(reverse|bind)[_\-\s]?shell",
            r"remote[_\-\s]?code[_\-\s]?execution",
            r"(exploit|attack)[_\-\s]?(vulnerability|weakness|system|target)",
            r"(contains|has|includes|provides|offers)[_\-\s]?(exploit|attack)[s]?",
            r"brute[_\-\s]?force",
        ]
        
        # Compile regex patterns for efficiency
        self.hidden_instruction_regex: List[re.Pattern] = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.hidden_instruction_patterns
        ]
        
        self.sensitive_file_regex: List[re.Pattern] = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.sensitive_file_patterns
        ]
        
        self.sensitive_action_regex: List[re.Pattern] = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.sensitive_action_patterns
        ]
        
        logging.info("Initialized ToolAnalyzer with security patterns")
    
    def check_patterns(self, description: str, pattern_regex: List[re.Pattern], 
                      pattern_strings: List[str], check_type: str) -> List[str]:
        """
        Generic pattern checking function for tool descriptions.
        
        Args:
            description (str): The tool description to analyze.
            pattern_regex (List[re.Pattern]): The compiled regex patterns to check against.
            pattern_strings (List[str]): The original pattern strings for reference.
            check_type (str): The type of check being performed (for logging).
            
        Returns:
            List[str]: A list of actual matched strings from the description, empty if none found.
        """
        if not description:
            logging.warning(f"Empty description provided for {check_type} check")
            return []
        
        matches: List[str] = []
        for pattern in pattern_regex:
            found_matches = pattern.findall(description)
            if found_matches:
                # Extract the actual matched strings
                for match in found_matches:
                    # Handle both string and tuple matches (capturing groups)
                    if isinstance(match, tuple):
                        # Join tuple elements for capturing groups
                        full_match = ' '.join(part for part in match if part)
                        matches.append(full_match)
                    else:
                        matches.append(match)
                
                pattern_str = pattern_strings[pattern_regex.index(pattern)]
                logging.debug(f"Pattern '{pattern_str}' matched: {found_matches}")
        
        if matches:
            logging.warning(f"Found {len(matches)} {check_type} patterns in description")
        
        return matches
    
    def analyze_tool_description(self, description: str) -> Dict[str, List[str]]:
        """
        Analyzes a tool description for all types of security concerns.
        
        Args:
            description (str): The tool description to analyze.
            
        Returns:
            Dict[str, List[str]]: A dictionary containing lists of matches for each category:
                                 'hidden_instructions', 'sensitive_files', 'sensitive_actions'
        """
        if not description:
            logger.debug("Empty description provided for analysis")
            return {
                "hidden_instructions": [],
                "sensitive_files": [],
                "sensitive_actions": []
            }
        
        results = {
            "hidden_instructions": self.check_patterns(
                description, 
                self.hidden_instruction_regex, 
                self.hidden_instruction_patterns, 
                "hidden instruction"
            ),
            "sensitive_files": self.check_patterns(
                description, 
                self.sensitive_file_regex, 
                self.sensitive_file_patterns, 
                "sensitive file"
            ),
            "sensitive_actions": self.check_patterns(
                description, 
                self.sensitive_action_regex, 
                self.sensitive_action_patterns, 
                "sensitive action"
            )
        }
        
        total_issues = sum(len(issues) for issues in results.values())
        if total_issues > 0:
            logger.debug(f"Found a total of {total_issues} security issues in the description")
        else:
            logger.debug("No security issues found in the description")
        
        return results
    
    def is_description_safe(self, description: str) -> Dict[str, Any]:
        """
        Determines if a tool description is safe based on the analysis results.
        
        Args:
            description (str): The tool description to analyze.
            
        Returns:
            Tuple[bool, Dict[str, List[str]]]: A tuple containing:
                - bool: True if the description is safe (no issues found), False otherwise
                - Dict: The detailed analysis results
        """
        results = self.analyze_tool_description(description)
        is_safe = all(len(issues) == 0 for issues in results.values())
            
        return {"is_safe": is_safe, "results": results}
    