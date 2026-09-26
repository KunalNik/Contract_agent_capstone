"""Build a small, valid text PDF in memory (no external dependencies)."""


def make_pdf(lines):
    def esc(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = "BT /F1 10 Tf 50 780 Td 14 TL\n" + "\n".join(f"({esc(l)}) Tj T*" for l in lines) + "\nET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


SAMPLE_CONTRACT_LINES = [
    "MASTER SERVICES AGREEMENT",
    "This Agreement is entered into on January 15, 2024 between Acme Corp and Beta LLC.",
    "1. Payment Terms. Client shall pay all invoices within ninety (90) days, net 90.",
    "2. Limitation of Liability. Supplier accepts unlimited liability for all claims.",
    "3. Termination. Either party may terminate this Agreement with thirty days notice.",
    "4. Governing Law. This Agreement is governed by the laws of the State of Delaware.",
]
