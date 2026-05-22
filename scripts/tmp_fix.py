    def _get_local_macro_value(self, local_name: str) -> str:
        """Helper: read a local macro value into a string variable then decode."""
        self._exe(b'capture drop __px_tmp')
        self._exe(f'capture gen str2000 __px_tmp = "`{local_name}\'"')
        return self.read_encoded_str('__px_tmp[1]', obs=1)
