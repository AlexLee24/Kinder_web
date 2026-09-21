import math

from astropy.coordinates import SkyCoord
import astropy.units as u
from psycopg2.extras import RealDictCursor
from tqdm import tqdm

from . import get_db_connection
from .healpix_index import cone_pixels, healpix_column


class CatalogueService:
    """Centralized catalog naming and type helpers for cross-match rows."""

    DESI_ALIASES = {"desi", "desi_dr", "desi_main"}
    LENS_PREFIX = "Lens_"

    @staticmethod
    def normalize_catalog_name(name: str) -> str:
        """Return canonical catalog name used in DB rows.

        Rules:
        - empty -> UNKNOWN
        - DESI aliases -> DESI
        - lens catalogs always start with Lens_ (single prefix only)
        """
        if not name:
            return "UNKNOWN"

        raw = str(name).strip()
        low = raw.lower()

        if low in CatalogueService.DESI_ALIASES:
            return "DESI"

        if low.startswith("lens_"):
            # Deduplicate repeated Lens_ prefixes: Lens_Lens_X -> Lens_X
            while low.startswith("lens_lens_"):
                raw = raw[5:]
                low = raw.lower()
            return raw

        if low.startswith("lens"):
            # Handle values like "lenskarp" or "lens_karp"
            clean = raw[4:].lstrip("_")
            return f"{CatalogueService.LENS_PREFIX}{clean}" if clean else "Lens_UNKNOWN"

        return raw

    @staticmethod
    def build_catalog_name(catalog_name: str | None, lens_catalog: str | None) -> str:
        if catalog_name:
            return CatalogueService.normalize_catalog_name(catalog_name)
        if lens_catalog:
            return CatalogueService.normalize_catalog_name(f"{CatalogueService.LENS_PREFIX}{lens_catalog}")
        return "DESI"

    @staticmethod
    def is_lens_catalog(catalog_name: str) -> bool:
        return str(catalog_name).strip().lower().startswith("lens_")

    @staticmethod
    def is_desi_catalog(catalog_name: str) -> bool:
        return str(catalog_name) == "DESI"

    # ---- spatial pre-filter (HEALPix pixel lookup, bounding box as fallback) ----

    _HEALPIX_COLUMN_CACHE: dict[tuple[str, str, str], bool] = {}

    @staticmethod
    def _has_healpix_column(cur, schema_name: str, table_name: str) -> bool:
        """Whether the table carries the precomputed pixel column for the current NSIDE."""
        column = healpix_column()
        key = (schema_name, table_name, column)
        cached = CatalogueService._HEALPIX_COLUMN_CACHE.get(key)
        if cached is not None:
            return cached

        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            LIMIT 1
            """,
            (schema_name, table_name, column),
        )
        exists = cur.fetchone() is not None
        if not exists:
            print(f"[WARNING] {schema_name}.{table_name} has no '{column}' column; using "
                  "bounding-box pre-filter. Run function/database/migrate_healpix.py "
                  "to build the HEALPix index.")
        CatalogueService._HEALPIX_COLUMN_CACHE[key] = exists
        return exists

    @staticmethod
    def _bounding_box_clause(ra: float, dec: float, search_radius_arcsec: float) -> tuple[str, list]:
        """Fallback pre-filter: RA/Dec box widened by 1/cos(dec), wrapping at RA 0/360."""
        radius_deg = search_radius_arcsec / 3600.0
        dec_min = max(dec - radius_deg, -90.0)
        dec_max = min(dec + radius_deg, 90.0)

        clause = " AND dec BETWEEN %s AND %s"
        params: list = [dec_min, dec_max]

        worst_dec = min(max(abs(dec_min), abs(dec_max)), 89.999999)
        cos_dec = math.cos(math.radians(worst_dec))
        ra_pad = 180.0 if cos_dec <= 0 else radius_deg / cos_dec
        if ra_pad >= 180.0:
            # Cone reaches around a pole: every RA is in range.
            return clause, params

        ra_min = ra - ra_pad
        ra_max = ra + ra_pad
        if ra_min < 0.0 or ra_max > 360.0:
            clause += " AND (ra >= %s OR ra <= %s)"
            params.extend([ra_min % 360.0, ra_max % 360.0])
        else:
            clause += " AND ra BETWEEN %s AND %s"
            params.extend([ra_min, ra_max])
        return clause, params

    @staticmethod
    def _spatial_filter(cur, schema_name: str, table_name: str,
                        ra: float, dec: float, search_radius_arcsec: float) -> tuple[str, list]:
        """SQL fragment (leading ' AND ') plus params selecting rows near the cone."""
        if CatalogueService._has_healpix_column(cur, schema_name, table_name):
            pixels = cone_pixels(ra, dec, search_radius_arcsec)
            return f' AND "{healpix_column()}" = ANY(%s)', [pixels]
        return CatalogueService._bounding_box_clause(ra, dec, search_radius_arcsec)

    # ---- DESI table layout -------------------------------------------------
    # v1: the original 7-column dump (desi_target_id, redshift, delta_chi_2 ...)
    # v2: the DR1 rebuild from build_desi_catalog.py (targetid, z, deltachi2, shapes, WISE ...)

    _DESI_LAYOUT_CACHE: dict[str, str] = {}

    # Columns the pipeline carries into match_data from the v2 table.
    DESI_V2_COLUMNS = (
        'survey', 'program', 'spectype', 'subtype', 'zcat_nspec', 'coadd_fiberstatus',
        'mean_fiber_ra', 'mean_fiber_dec', 'mean_mjd',
        'ls_id', 'release', 'morphtype', 'sersic', 'shape_r', 'shape_e1', 'shape_e2',
        'flux_g', 'flux_r', 'flux_z', 'flux_w1', 'flux_w2', 'flux_w3', 'flux_w4',
        'flux_ivar_w1', 'flux_ivar_w2', 'mw_transmission_w1', 'mw_transmission_w2',
        'fiberflux_r', 'fracflux_r', 'ebv', 'maskbits',
        'gaia_phot_g_mean_mag', 'parallax', 'pmra', 'pmdec',
        'dr10_ra', 'dr10_dec', 'dr10_type', 'dr10_sersic', 'dr10_shape_r', 'dr10_shape_e1', 'dr10_shape_e2',
        'dr10_flux_r', 'dr10_sep',
        'mass_cg', 'masserr_cg', 'sfr_cg', 'sfrerr_cg', 'age_cg', 'av_cg',
        'masscor_sl', 'vd_sl', 'age_sl', 'dn4000', 'dn4000_err', 'snr_med',
        'agn_maskbits', 'opt_uv_type', 'ir_type', 'agn_logmstar', 'data_release',
    )

    @staticmethod
    def desi_layout(cur) -> str:
        """'v2' when cat.desi has the DR1 rebuild columns, else 'v1'."""
        cached = CatalogueService._DESI_LAYOUT_CACHE.get('desi')
        if cached:
            return cached
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'cat' AND table_name = 'desi' AND column_name = 'targetid'
            LIMIT 1
            """
        )
        layout = 'v2' if cur.fetchone() else 'v1'
        CatalogueService._DESI_LAYOUT_CACHE['desi'] = layout
        return layout

    @staticmethod
    def fetch_desi_candidates(cur, ra: float, dec: float, search_radius_arcsec: float,
                              include_stars: bool = False) -> list[dict]:
        """Rows of cat.desi near (ra, dec), best spectrum first.

        Whatever the table layout, the returned dicts carry the legacy keys the
        rest of the pipeline reads ("TARGETID", ra, dec, z, redshift_err,
        delta_chi_2, zwarn); the v2 layout adds the columns in DESI_V2_COLUMNS.
        Stars are left out unless asked for — the host rule can never pick one,
        and they would only inflate the DESI match count.
        """
        clause, params = CatalogueService._spatial_filter(
            cur, "cat", "desi", ra, dec, search_radius_arcsec
        )
        if CatalogueService.desi_layout(cur) == 'v2':
            extra = ", ".join(f'"{c}"' for c in CatalogueService.DESI_V2_COLUMNS)
            query = (
                'SELECT targetid AS "TARGETID", ra, dec, z, zerr AS redshift_err, '
                'deltachi2 AS delta_chi_2, zwarn, ' + extra +
                " FROM cat.desi WHERE TRUE" + clause
            )
            if not include_stars:
                query += " AND spectype <> 'STAR'"
        else:
            query = (
                'SELECT desi_target_id AS "TARGETID", ra, dec, '
                'redshift AS z, redshift_err, delta_chi_2, zwarn '
                "FROM cat.desi WHERE TRUE" + clause
            )
        # Best spectrum first, so a TARGETID observed in several survey/program
        # combinations dedupes to its most reliable redshift downstream.
        query += " ORDER BY zwarn ASC NULLS LAST, delta_chi_2 DESC NULLS LAST"
        cur.execute(query, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def fetch_desi_stars(cur, ra: float, dec: float, radius_arcsec: float) -> list[dict]:
        """DESI STAR spectra within the cone (v2 layout only), with separation_arcsec."""
        if CatalogueService.desi_layout(cur) != 'v2':
            return []
        clause, params = CatalogueService._spatial_filter(cur, "cat", "desi", ra, dec, radius_arcsec)
        cur.execute(
            'SELECT targetid AS "TARGETID", ra, dec, z, zwarn, spectype, subtype, '
            'gaia_phot_g_mean_mag, parallax, pmra, pmdec, mag_r '
            "FROM cat.desi WHERE spectype = 'STAR'" + clause,
            tuple(params),
        )
        target = SkyCoord(ra=ra * u.degree, dec=dec * u.degree, frame="icrs")
        out = []
        for r in cur.fetchall():
            row = dict(r)
            sep = target.separation(SkyCoord(ra=row["ra"] * u.degree, dec=row["dec"] * u.degree)).arcsec
            if sep <= radius_arcsec:
                row["separation_arcsec"] = round(float(sep), 3)
                out.append(row)
        return out

    @staticmethod
    def _catalog_table_exists(cur, schema_name: str, table_name: str) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
            LIMIT 1
            """,
            (schema_name, table_name),
        )
        return cur.fetchone() is not None

    @staticmethod
    def _lens_table_candidates(catalog_name: str) -> list[str]:
        suffix = catalog_name[len(CatalogueService.LENS_PREFIX):].strip()
        slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in suffix).strip("_")
        while "__" in slug:
            slug = slug.replace("__", "_")

        candidates: list[str] = []
        if slug:
            candidates.extend([f"lens_{slug}", slug])
            if slug == "catalogue":
                candidates.extend(["lens_catalog", "catalog"])
        # Current DB layout stores all lens rows in cat.lens.
        candidates.append("lens")

        # Keep order stable while removing duplicates/empties.
        return [name for i, name in enumerate(candidates) if name and name not in candidates[:i]]

    @staticmethod
    def _resolve_lens_table(cur, catalog_name: str) -> str:
        for table_name in CatalogueService._lens_table_candidates(catalog_name):
            if CatalogueService._catalog_table_exists(cur, "cat", table_name):
                return table_name
        raise ValueError(f"Unsupported catalog for DB cross-match: {catalog_name}")

    @staticmethod
    def fetch_lens_candidates(
        cur,
        table_name: str,
        ra: float,
        dec: float,
        search_radius_arcsec: float,
        reference_keyword: str | None = None,
    ) -> list[dict]:
        if not table_name.replace("_", "").isalnum():
            raise ValueError(f"Unsafe lens table name: {table_name}")

        clause, params = CatalogueService._spatial_filter(
            cur, "cat", table_name, ra, dec, search_radius_arcsec
        )
        query = f"SELECT * FROM cat.{table_name} WHERE TRUE" + clause
        if reference_keyword:
            query += " AND COALESCE(reference, '') ILIKE %s"
            params.append(f"%{reference_keyword}%")
        cur.execute(query, tuple(params))

        # SELECT * would otherwise leak the internal pixel column into match_data.
        pixel_column = healpix_column()
        rows = []
        for record in cur.fetchall():
            row = dict(record)
            row.pop(pixel_column, None)
            rows.append(row)
        return rows

    @staticmethod
    def _lens_reference_keyword(catalog_name: str) -> str | None:
        low = catalog_name.lower()
        if low == "lens_karp":
            return "karp"
        if low == "lens_hsu":
            return "hsu"
        return None

    @staticmethod
    def cross_match_desi(target_list, search_radius: float = 30) -> dict:
        """Cross match targets against DESI catalog in PostgreSQL."""
        all_matched_data: dict = {}

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for ra, dec, target_name in tqdm(target_list, desc="Processing DESI", unit="obj"):
                    matched_data = []
                    candidates = CatalogueService.fetch_desi_candidates(cur, ra, dec, search_radius)
                    target_coord = SkyCoord(ra=ra * u.degree, dec=dec * u.degree, frame="icrs")

                    for row in candidates:
                        source_coord = SkyCoord(
                            ra=row["ra"] * u.degree,
                            dec=row["dec"] * u.degree,
                            frame="icrs",
                        )
                        separation = target_coord.separation(source_coord).arcsec
                        if separation <= search_radius:
                            row["separation_arcsec"] = separation
                            matched_data.append(row)

                    all_matched_data[target_name] = matched_data

        return all_matched_data

    @staticmethod
    def cross_match_lens(target_list, catalog_name: str, search_radius: float = 30) -> dict:
        """Cross match targets against one of the lens catalogs in PostgreSQL."""
        all_matched_data: dict = {}

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                table_name = CatalogueService._resolve_lens_table(cur, catalog_name)
                reference_keyword = CatalogueService._lens_reference_keyword(catalog_name)
                for ra, dec, target_name in tqdm(target_list, desc=f"Processing {catalog_name}", unit="obj"):
                    matched_data = []
                    candidates = CatalogueService.fetch_lens_candidates(
                        cur,
                        table_name,
                        ra,
                        dec,
                        search_radius,
                        reference_keyword=reference_keyword,
                    )
                    target_coord = SkyCoord(ra=ra * u.degree, dec=dec * u.degree, frame="icrs")

                    for row in candidates:
                        source_coord = SkyCoord(
                            ra=row["ra"] * u.degree,
                            dec=row["dec"] * u.degree,
                            frame="icrs",
                        )
                        separation = target_coord.separation(source_coord).arcsec
                        if separation <= search_radius:
                            row["origin_catalog_name"] = catalog_name
                            row["separation_arcsec"] = separation
                            matched_data.append(row)

                    all_matched_data[target_name] = matched_data

        return all_matched_data

    @staticmethod
    def cross_match_catalog(target_list, catalog_name: str, search_radius: float = 30) -> dict:
        normalized = CatalogueService.normalize_catalog_name(catalog_name)
        if CatalogueService.is_desi_catalog(normalized):
            return CatalogueService.cross_match_desi(target_list, search_radius=search_radius)
        if CatalogueService.is_lens_catalog(normalized):
            return CatalogueService.cross_match_lens(target_list, normalized, search_radius=search_radius)
        raise ValueError(f"Unsupported catalog for DB cross-match: {normalized}")
