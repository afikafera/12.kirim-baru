class QueryStrategy:
    """
    Memetakan user query ke extraction method dan source type.

    Domain-independent:
    tidak mengetahui speaker, otomotif, networking, dll.
    """

    def _source_type(self, query: str) -> str:
        if not isinstance(query, str):
            return "TEXT"

        q = query.lower().strip()

        graph_keywords = (
            "grafik frekuensi",
            "frequency graph",
            "response curve",
            "grafik impedansi",
            "impedance graph",
        )

        geometry_keywords = (
            "ukuran",
            "dimensi",
            "diameter",
            "panjang",
            "lebar",
            "tinggi",
            "gambar kerja",
            "technical drawing",
        )

        datasheet_keywords = (
            "datasheet",
            "data sheet",
            "spek teknis",
            "spesifikasi teknis",
            "technical specification",
        )

        if any(keyword in q for keyword in graph_keywords):
            if "impedansi" in q or "impedance" in q:
                return "IMPEDANCE_GRAPH"
            return "FREQUENCY_GRAPH"

        if any(keyword in q for keyword in geometry_keywords):
            return "TECHNICAL_DRAWING"

        if any(keyword in q for keyword in datasheet_keywords):
            return "DATASHEET"

        return "TEXT"

    def source_type(self, query: str) -> str:
        return self._source_type(query)

    def route(self, query: str) -> str:
        """
        Backward-compatible API:
        route() tetap mengembalikan extraction method.
        """
        routes = {
            "TEXT": "text_extract",
            "DATASHEET": "ocr_extract",
            "TECHNICAL_DRAWING": "visual_geometry",
            "FREQUENCY_GRAPH": "graph_analysis",
            "IMPEDANCE_GRAPH": "graph_analysis",
        }

        return routes.get(self._source_type(query), "text_extract")
