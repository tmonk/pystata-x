    def get_temp_name(self, prefix: str = '') -> str:
        """Get a temp name from Stata (prefix used if provided)."""
        pfx = prefix if prefix else 'px'
        # Create a temporary name using Stata string + random
        self._exe(b'capture local __px_tn : di "' + pfx.encode() + b'\\x60 + string(floor(runiform()*1e12))')
        self._exe(b'capture drop __px_tmp')
        # Gen a string variable from the local macro
        self._exe(b'capture gen str2000 __px_tmp = "\\x60__px_tn\\x27"')
        return self.read_encoded_str('__px_tmp[1]', obs=1)
