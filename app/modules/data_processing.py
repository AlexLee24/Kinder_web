import logging
import math
import numpy as np
import plotly.graph_objects as go
import plotly.offline as pyo
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Import external module for absolute magnitude calculation
try:
    from . import ext_M_calculator
except ImportError:
    try:
        from modules import ext_M_calculator
    except ImportError:
        ext_M_calculator = None

class DataVisualization:
    
    @staticmethod
    def get_filter_color(filter_name, alpha=1):
        """Get color for a filter. Loads from app/data/filter_colors.json; alpha applied dynamically."""
        try:
            from modules import filter_colors as _fc
        except ImportError:
            from . import filter_colors as _fc
        return _fc.get_rgba(filter_name, alpha)

    @staticmethod
    def _apply_unified_plot_style(layout, legend_right=True):
        """Apply a shared dark-panel Plotly style across photometry/spectroscopy charts."""
        layout.update(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#ccc'),
            hoverlabel=dict(
                bgcolor='rgba(20,20,20,0.95)',
                bordercolor='rgba(140,140,140,0.6)',
                font=dict(color='#eee')
            )
        )

        if layout.legend:
            layout.legend.update(
                bgcolor='rgba(20,20,20,0.55)',
                bordercolor='rgba(140,140,140,0.35)',
                borderwidth=1,
                font=dict(color='#ddd')
            )
            if legend_right:
                # Only set position when the caller hasn't already placed it
                if layout.legend.x is None:
                    layout.legend.update(
                        x=0.99, y=0.99, xanchor='right', yanchor='top',
                        bgcolor='rgba(12,12,20,0.72)',
                        bordercolor='rgba(160,160,160,0.25)',
                        borderwidth=1,
                    )

        axis_style = dict(
            showline=True,
            linecolor='rgba(180,180,180,0.55)',
            tickcolor='rgba(180,180,180,0.55)',
            gridcolor='rgba(120,120,120,0.25)',
            zerolinecolor='rgba(120,120,120,0.25)'
        )
        for axis_name in ('xaxis', 'xaxis2', 'yaxis', 'yaxis2'):
            axis_obj = getattr(layout, axis_name, None)
            if axis_obj:
                axis_obj.update(**axis_style)

        return layout
    
    @staticmethod
    def create_photometry_plot_from_db(photometry_data, redshift=None, ra=None, dec=None, as_json=False, apply_extinction=True, apply_k_corr=True):
        """Create interactive photometry plot from database data"""
        if not photometry_data:
            return None
            
        # Ensure redshift, ra, dec are floats
        try:
            redshift = float(redshift) if redshift is not None else None
        except (ValueError, TypeError):
            redshift = None
            
        try:
            ra = float(ra) if ra is not None else None
        except (ValueError, TypeError):
            ra = None
            
        try:
            dec = float(dec) if dec is not None else None
        except (ValueError, TypeError):
            dec = None
        
        # ── TNS deduplication ──────────────────────────────────────────────────
        # Rule 1: suppress a TNS point when any non-TNS point shares the same
        #         filter and falls within 1 day.
        # Rule 2: among TNS points with the same filter+telescope, keep only the
        #         first one per 1-day window (deduplicate TNS self-repetition).
        def _is_tns(telescope_str):
            return 'tns' in str(telescope_str).lower()

        TNS_DEDUP_WINDOW = 1.0  # days

        # Pre-parse to floats for fast comparison
        _pts = []
        for p in photometry_data:
            try:
                mjd_f = float(p.get('mjd')) if p.get('mjd') is not None else None
            except (ValueError, TypeError):
                mjd_f = None
            _pts.append((p, mjd_f))

        # Build a lookup: filter -> list of (mjd) for NON-TNS points
        _non_tns_by_filter = {}
        for p, mjd_f in _pts:
            if mjd_f is None:
                continue
            tel = p.get('telescope', 'Unknown')
            if not _is_tns(tel):
                flt = p.get('filter', 'Unknown')
                _non_tns_by_filter.setdefault(flt, []).append(mjd_f)

        # Walk TNS points in (filter, telescope) order, tracking seen windows
        _tns_seen = {}   # (filter, telescope) -> list of accepted mjds
        _keep_flags = []
        for p, mjd_f in _pts:
            tel = p.get('telescope', 'Unknown')
            flt = p.get('filter', 'Unknown')
            if not _is_tns(tel) or mjd_f is None:
                _keep_flags.append(True)
                continue

            # Rule 1: any non-TNS point within 1 day for same filter?
            non_tns_mjds = _non_tns_by_filter.get(flt, [])
            if any(abs(mjd_f - m) < TNS_DEDUP_WINDOW for m in non_tns_mjds):
                _keep_flags.append(False)
                continue

            # Rule 2: already accepted a TNS point within 1 day for same filter?
            # Use filter only — telescope names like "ZTF (TNS)" vs "ZTF(TNS)" are
            # the same source and should be treated as one group.
            key = flt
            accepted = _tns_seen.get(key, [])
            if any(abs(mjd_f - m) < TNS_DEDUP_WINDOW for m in accepted):
                _keep_flags.append(False)
                continue

            # Keep this point
            _tns_seen.setdefault(flt, []).append(mjd_f)
            _keep_flags.append(True)

        photometry_data = [p for (p, _), keep in zip(_pts, _keep_flags) if keep]
        # ── end TNS deduplication ───────────────────────────────────────────

        # Group data by filter and telescope
        grouped_data = {}
        
        all_mjds = []
        all_mags = []
        
        for point in photometry_data:
            # Safely get and cast values
            mjd = point.get('mjd')
            try:
                mjd = float(mjd) if mjd is not None else None
            except (ValueError, TypeError):
                mjd = None
                
            mag = point.get('magnitude')
            try:
                mag = float(mag) if mag is not None else None
            except (ValueError, TypeError):
                mag = None
                
            err = point.get('magnitude_error')
            try:
                err = float(err) if err is not None else None
                # Check for NaN
                if err is not None and (err != err):  # NaN check
                    err = None
            except (ValueError, TypeError):
                err = None

            if mjd is not None:
                all_mjds.append(mjd)
            if mag is not None:
                all_mags.append(mag)
                
            filter_name = point.get('filter', 'Unknown')
            telescope = point.get('telescope', 'Unknown')
            key = f"{filter_name}_{telescope}"
            
            if key not in grouped_data:
                grouped_data[key] = {
                    'mjd': [],
                    'magnitude': [],
                    'magnitude_error': [],
                    'filter': filter_name,
                    'telescope': telescope
                }
            
            grouped_data[key]['mjd'].append(mjd)
            grouped_data[key]['magnitude'].append(mag)
            grouped_data[key]['magnitude_error'].append(err)
        
        # Calculate distance modulus and extinction shift
        distance_modulus = 0
        k_correction = 0
        extinction_shift = 0
        ref_filter = 'r'
        
        if redshift and redshift > 0 and ext_M_calculator:
            try:
                # Use ext_M_calculator for distance
                distance_mpc, _ = ext_M_calculator.z_to_lmd(redshift)
                if isinstance(distance_mpc, (int, float)):
                    distance_modulus = 5 * math.log10(distance_mpc * 1e6) - 5
                    if apply_k_corr:
                        k_correction = 2.5 * math.log10(1 + redshift)
                    
                    # Calculate extinction if RA/Dec available
                    if ra is not None and dec is not None and apply_extinction:
                        # Use V band as reference for the axis
                        ref_filter = 'V'
                        
                        extinction_shift = ext_M_calculator.get_extinction(ra, dec, ref_filter)
                        if not isinstance(extinction_shift, (int, float)):
                            extinction_shift = 0
            except Exception as e:
                logger.error('Error calculating absolute magnitude parameters: %s', e)
                distance_modulus = 0
        elif redshift and redshift > 0:
            # Fallback to simple calculation if module not available
            try:
                c = 299792.458 # km/s
                H0 = 70.0 # km/s/Mpc
                d_L_Mpc = (c * redshift) / H0
                distance_modulus = 5 * np.log10(d_L_Mpc * 1e6) - 5
            except Exception:
                distance_modulus = 0
        
        total_shift = distance_modulus + k_correction + extinction_shift
        
        # Create traces for each group
        traces = []
        marker_symbols = ['circle', 'square', 'diamond', 'cross', 'x', 'star']
        
        # Assign a consistent symbol for each telescope
        telescope_symbols = {}
        symbol_index = 0
        
        # First pass to assign symbols
        for group_key, data in grouped_data.items():
            telescope = data['telescope']
            if telescope not in telescope_symbols:
                if telescope == 'Unknown':
                    telescope_symbols[telescope] = 'circle'
                else:
                    telescope_symbols[telescope] = marker_symbols[symbol_index % len(marker_symbols)]
                    symbol_index += 1

        for group_key, data in grouped_data.items():
            filter_name = data['filter']
            telescope = data['telescope']
            
            # Calculate specific absolute magnitude for this filter
            filter_specific_shift = distance_modulus
            if apply_k_corr:
                filter_specific_shift += k_correction
            if apply_extinction and ra is not None and dec is not None and ext_M_calculator:
                try:
                    ext = ext_M_calculator.get_extinction(ra, dec, filter_name)
                    if isinstance(ext, (int, float)):
                        filter_specific_shift += ext
                except Exception:
                    pass
            
            # Get symbol for telescope
            symbol = telescope_symbols.get(telescope, 'circle')
            
            # Separate points with and without errors
            # Upper limits: magnitude_error is None or NaN (non-detection)
            with_errors = []
            without_errors = []
            
            for i, error in enumerate(data['magnitude_error']):
                if error is not None and error == error and error > 0:  # Valid positive error
                    with_errors.append(i)
                else:
                    # None, NaN, or 0 => upper limit (non-detection)
                    without_errors.append(i)
            
            # Add trace for points with error bars
            if with_errors:
                # Calculate absolute magnitudes and store errors for hover
                custom_data = []
                for i in with_errors:
                    mag = data['magnitude'][i]
                    err = data['magnitude_error'][i]
                    abs_mag = (mag - filter_specific_shift) if mag is not None else None
                    custom_data.append([abs_mag, err])
                        
                trace_with_errors = go.Scatter(
                    x=[data['mjd'][i] for i in with_errors],
                    y=[data['magnitude'][i] for i in with_errors],
                    customdata=custom_data,
                    mode='markers',
                    name=f'{filter_name} ({telescope})',
                    marker=dict(
                        color=DataVisualization.get_filter_color(filter_name),
                        symbol=symbol,
                        size=8
                    ),
                    error_y=dict(
                        type='data',
                        array=[data['magnitude_error'][i] for i in with_errors],
                        visible=True,
                        color=DataVisualization.get_filter_color(filter_name)
                    ),
                    hovertemplate='<b>%{fullData.name}</b><br>' +
                                  'MJD: %{x:.3f}<br>' +
                                  'App. Mag: %{y:.3f} ± %{customdata[1]:.3f}<br>' +
                                  'Abs. Mag: %{customdata[0]:.3f}<br>' +
                                  '<extra></extra>'
                )
                traces.append(trace_with_errors)
            
            # Add trace for upper limits (points without errors)
            if without_errors:
                # Calculate absolute magnitudes for hover
                abs_mags = []
                for i in without_errors:
                    mag = data['magnitude'][i]
                    if mag is not None:
                        abs_mags.append(mag - filter_specific_shift)
                    else:
                        abs_mags.append(None)

                trace_upper_limits = go.Scatter(
                    x=[data['mjd'][i] for i in without_errors],
                    y=[data['magnitude'][i] for i in without_errors],
                    customdata=abs_mags,
                    mode='markers',
                    name=f'{filter_name} ({telescope}) - Up',
                    marker=dict(
                        color=DataVisualization.get_filter_color(filter_name),
                        symbol='triangle-down-open',
                        size=8,
                        line=dict(width=2)
                    ),
                    hovertemplate='<b>%{fullData.name}</b><br>' +
                                  'MJD: %{x:.3f}<br>' +
                                  'App. Mag: %{y:.3f} (Up)<br>' +
                                  'Abs. Mag: >%{customdata:.3f}<br>' +
                                  '<extra></extra>'
                )
                traces.append(trace_upper_limits)
        
        if not traces:
            return None
            
        # Determine ranges — enforce a minimum 5-day default span (5 grids × 1 day each)
        min_mjd = min(all_mjds) if all_mjds else 59000
        max_mjd = max(all_mjds) if all_mjds else 59100
        data_span = max_mjd - min_mjd
        GRID_INTERVAL_DAYS = 1      # each grid cell = 1 day
        MIN_GRID_CELLS     = 5      # always show at least 5 cells
        MIN_SPAN_DAYS      = GRID_INTERVAL_DAYS * MIN_GRID_CELLS  # = 5 days
        if data_span < MIN_SPAN_DAYS:
            # Center the minimum window on the data
            center_mjd = (min_mjd + max_mjd) / 2
            plot_min_mjd = center_mjd - MIN_SPAN_DAYS / 2
            plot_max_mjd = center_mjd + MIN_SPAN_DAYS / 2
        else:
            pad_mjd = data_span * 0.05
            if pad_mjd == 0: pad_mjd = GRID_INTERVAL_DAYS
            plot_min_mjd = min_mjd - pad_mjd
            plot_max_mjd = max_mjd + pad_mjd

        # Helper to convert MJD to Date string
        def mjd_to_date_str(mjd):
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=mjd - 40587)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
            
        plot_min_date = mjd_to_date_str(plot_min_mjd)
        plot_max_date = mjd_to_date_str(plot_max_mjd)
        
        # Build xaxis config — if data span is under the minimum window, lock ticks to grid interval
        _xaxis_extra = {}
        if data_span < MIN_SPAN_DAYS:
            _xaxis_extra = dict(
                tickmode='linear',
                dtick=GRID_INTERVAL_DAYS,
                tick0=math.floor(plot_min_mjd)
            )

        # Create layout
        layout = go.Layout(
            title="Photometry Light Curve",
            xaxis=dict(
                title="Modified Julian Date (MJD)",
                tickformat=".2f",
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)',
                range=[plot_min_mjd, plot_max_mjd],
                **_xaxis_extra
            ),
            xaxis2=dict(
                title="Date (UTC)",
                overlaying='x',
                side='top',
                type='date',
                range=[plot_min_date, plot_max_date],
                showgrid=False
            ),
            yaxis=dict(
                title="App Mag",
                tickformat=".2f",
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)'
            ),
            template="plotly_white",
            showlegend=True,
            legend=dict(
                orientation='h',
                x=0.5,
                y=1.10,
                xanchor='left',
                yanchor='bottom',
                bgcolor='rgba(12,12,20,0.72)',
                bordercolor='rgba(160,160,160,0.25)',
                borderwidth=1,
            ),
            hovermode='closest',
            margin=dict(l=60, r=60, t=95, b=60)
        )
        
        # Handle Y-axis range and Absolute Magnitude.
        # Mirror the x-axis behaviour: when the magnitude span is small, enforce a
        # minimum window and lock ticks to a fixed grid.
        GRID_INTERVAL_MAG = 0.2     # each grid cell = 0.2 mag
        MIN_GRID_CELLS_MAG = 6      # always show at least 6 cells
        MIN_SPAN_MAG = GRID_INTERVAL_MAG * MIN_GRID_CELLS_MAG  # = 3.0 mag
        plot_min_mag = 0.0
        plot_max_mag = 0.0
        if all_mags:
            min_mag = min(all_mags)
            max_mag = max(all_mags)
            mag_span = max_mag - min_mag
            if mag_span < MIN_SPAN_MAG:
                # Center the minimum window on the data and lock ticks to the grid
                center_mag = (min_mag + max_mag) / 2
                plot_min_mag = center_mag - MIN_SPAN_MAG / 2
                plot_max_mag = center_mag + MIN_SPAN_MAG / 2
                layout.yaxis.tickmode = 'linear'
                layout.yaxis.dtick = GRID_INTERVAL_MAG
                layout.yaxis.tick0 = math.floor(plot_min_mag / GRID_INTERVAL_MAG) * GRID_INTERVAL_MAG
            else:
                mag_pad = mag_span * 0.1
                if mag_pad == 0: mag_pad = GRID_INTERVAL_MAG
                plot_min_mag = min_mag - mag_pad
                plot_max_mag = max_mag + mag_pad

            # Reversed Y-axis: [max, min]
            layout.yaxis.range = [plot_max_mag, plot_min_mag]

            if total_shift > 0:
                abs_min = plot_min_mag - total_shift
                abs_max = plot_max_mag - total_shift
            else:
                # No redshift — mirror the apparent-mag axis so the right axis
                # still renders (labelled "Abs Mag" with N/A hint in title).
                abs_min = plot_min_mag
                abs_max = plot_max_mag

            layout.yaxis2 = dict(
                title="Abs Mag" if total_shift > 0 else "Abs Mag (z N/A)",
                overlaying='y',
                side='right',
                range=[abs_max, abs_min],
                showgrid=False,
                tickformat=".2f",
                showticklabels=total_shift > 0,
            )
            # Keep the absolute-mag ticks on the same 0.5-mag grid when locked
            if mag_span < MIN_SPAN_MAG and total_shift > 0:
                layout.yaxis2.update(tickmode='linear', dtick=GRID_INTERVAL_MAG)

            # Add dummy trace to force yaxis2 to appear
            traces.append(go.Scatter(
                x=[plot_min_mjd],
                y=[abs_max],
                xaxis='x',
                yaxis='y2',
                mode='markers',
                marker=dict(opacity=0),
                showlegend=False,
                hoverinfo='skip'
            ))
        else:
             layout.yaxis.autorange = "reversed"
             
        # Add dummy trace to force xaxis2 to appear
        traces.append(go.Scatter(
            x=[plot_min_date, plot_max_date],
            y=[plot_min_mag, plot_max_mag] if all_mags else [0, 0],
            xaxis='x2',
            yaxis='y',
            mode='markers',
            marker=dict(opacity=0),
            showlegend=False,
            hoverinfo='skip'
        ))

        layout = DataVisualization._apply_unified_plot_style(layout, legend_right=False)

        fig = go.Figure(data=traces, layout=layout)
        
        if as_json:
            return fig.to_json()
        
        # Convert to HTML div
        plot_div = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        return plot_div
    
    @staticmethod
    @staticmethod
    def _yrange_from_window(all_wls, all_ints, w_min=4500, w_max=7000, pad=0.12):
        """Return [ymin, ymax] from 4500-7000 Å window (2nd/98th pct + padding).
        Falls back to None (autorange) if window has no data."""
        import numpy as np
        vals = [
            v
            for wls, ints in zip(all_wls, all_ints)
            for w, v in zip(wls, ints)
            if w is not None and v is not None and w_min <= w <= w_max
        ]
        if not vals:
            return None
        arr = np.array(vals, dtype=float)
        lo = float(np.percentile(arr, 2))
        hi = float(np.percentile(arr, 98))
        span = hi - lo or abs(hi) * 0.1 or 0.1
        return [lo - span * pad, hi + span * pad]

    @staticmethod
    def _window_norm_scale(wavelengths, intensities, w_min=5000, w_max=7000):
        """Compute normalisation scale using median flux in [w_min, w_max] Å window.
        Falls back to 98th-percentile of full spectrum if window is empty."""
        import numpy as np
        window_vals = [
            v for w, v in zip(wavelengths, intensities)
            if w is not None and v is not None and w_min <= w <= w_max
        ]
        if window_vals:
            arr = np.abs(np.array(window_vals, dtype=float))
            scale = np.median(arr)
        else:
            arr = np.abs(np.array([v for v in intensities if v is not None], dtype=float))
            scale = np.percentile(arr, 98) if len(arr) else 1.0
        return float(scale) if scale and scale > 0 else float(np.max(arr)) or 1.0

    @staticmethod
    def create_spectrum_plot_from_db(spectrum_data, spectrum_id, rest_frame=False, redshift=None, normalise=False):
        """Create interactive spectrum plot from database data"""
        if not spectrum_data:
            return None
        
        # Filter data for specific spectrum_id
        spectrum_points = [point for point in spectrum_data if point.get('spectrum_id') == spectrum_id]
        
        if not spectrum_points:
            return None
        
        # Sort by wavelength
        spectrum_points.sort(key=lambda x: x.get('wavelength', 0))
        
        wavelengths = [point.get('wavelength') for point in spectrum_points]
        intensities = [point.get('intensity') for point in spectrum_points]
        
        # Apply rest-frame correction
        if rest_frame and redshift is not None:
            z = float(redshift)
            wavelengths = [w / (1 + z) if w is not None else None for w in wavelengths]
        
        # Apply normalisation: median flux in 5000-7000 Å window (rest or observed)
        if normalise and intensities:
            norm_scale = DataVisualization._window_norm_scale(wavelengths, intensities)
            intensities = [v / norm_scale if v is not None else None for v in intensities]
        
        # Get spectrum metadata
        telescope = spectrum_points[0].get('telescope', 'Unknown')
        phase = spectrum_points[0].get('phase')
        spectrum_label = spectrum_points[0].get('spectrum_label') or telescope or 'Spectrum'
        
        x_label = 'Rest-frame Wavelength (Å)' if (rest_frame and redshift is not None) else 'Wavelength (Å)'
        y_label = 'Normalized Intensity' if normalise else 'Relative Intensity'
        
        # Compute y-range from 4500-7000 Å window to avoid noise dominating the view
        yrange = DataVisualization._yrange_from_window([wavelengths], [intensities])
        yaxis_cfg: dict = dict(title=y_label, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
        if yrange:
            yaxis_cfg['range'] = yrange

        # Create trace
        # Emerald green sits in a gap between the spectral-line overlay hues (see
        # SPECTRUM_TRACE_COLORS) so the data line never blends into a line marker.
        trace = go.Scatter(
            x=wavelengths,
            y=intensities,
            mode='lines',
            name=spectrum_label,
            line=dict(
                color='#3ddc84',
                width=1.5
            ),
            hovertemplate=f'<b>{spectrum_label}</b><br>' +
                          'Wavelength: %{x:.1f} Å<br>' +
                          'Intensity: %{y:.3e}<br>' +
                          '<extra></extra>'
        )
        
        # Create layout
        title_text = spectrum_label
        if phase is not None:
            title_text += f" (Phase: {phase:.1f} days)"

        layout = go.Layout(
            # Left-aligned so it never collides with spectral-line labels at the top centre
            title=dict(text=title_text, x=0.01, xanchor='left',
                       font=dict(size=13, color='#9aa0a6')),
            xaxis=dict(
                title=x_label,
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)'
            ),
            yaxis=yaxis_cfg,
            template="plotly_white",
            showlegend=False,
            hovermode='x unified',
            margin=dict(l=60, r=60, t=50, b=60)
        )
        layout = DataVisualization._apply_unified_plot_style(layout, legend_right=False)
        
        fig = go.Figure(data=[trace], layout=layout)
        
        # Convert to HTML div
        plot_div = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        return plot_div
    
    @staticmethod
    def create_spectrum_list_plot_from_db(spectrum_data, rest_frame=False, redshift=None, normalise=False, stack=False):
        """Create plot showing all available spectra for an object"""
        if not spectrum_data:
            return None
        
        # Group by spectrum_id
        spectrum_groups = {}
        for point in spectrum_data:
            spectrum_id = point.get('spectrum_id')
            if spectrum_id not in spectrum_groups:
                spectrum_groups[spectrum_id] = []
            spectrum_groups[spectrum_id].append(point)
        
        traces = []
        all_wls_for_range = []   # collect processed wavelengths for y-range
        all_ints_for_range = []  # collect processed intensities for y-range
        # Vivid, but chosen to fall in the HUE GAPS between the 14 spectral-line
        # overlay colours (object_detail.js _SPEC_LINE_COLORS) so a data trace never
        # matches a line marker: emerald(130°), indigo(240°), purple(296°), rose(345°),
        # then a darker emerald and a lighter indigo for the 5th/6th spectra.
        colors = ['#3ddc84', '#6c7bf0', '#cf6be0', '#f76a87', '#28a866', '#a9b2f7']
        
        for i, (spectrum_id, points) in enumerate(spectrum_groups.items()):
            # Sort by wavelength
            points.sort(key=lambda x: x.get('wavelength', 0))
            
            wavelengths = [point.get('wavelength') for point in points]
            intensities = [point.get('intensity') for point in points]
            
            # Apply rest-frame correction
            if rest_frame and redshift is not None:
                z = float(redshift)
                wavelengths = [w / (1 + z) if w is not None else None for w in wavelengths]
            
            # Normalise: window-based (5000-7000 Å) when requested;
            # always apply basic 98th-pct scale in list view for readable comparison
            if normalise and intensities:
                norm_scale = DataVisualization._window_norm_scale(wavelengths, intensities)
            else:
                import numpy as np
                arr = np.abs(np.array([v for v in intensities if v is not None], dtype=float))
                norm_scale = np.percentile(arr, 98) if len(arr) else 1.0
                if norm_scale == 0:
                    norm_scale = np.max(arr) or 1.0
            intensities = [v / norm_scale if v is not None else None for v in intensities]
            
            # Apply vertical offset per spectrum only when stack=True
            if stack:
                intensities = [v + i * 1.2 if v is not None else None for v in intensities]
            
            all_wls_for_range.append(wavelengths)
            all_ints_for_range.append(intensities)
            
            telescope = points[0].get('telescope', 'Unknown')
            phase = points[0].get('phase')
            spectrum_label = points[0].get('spectrum_label') or spectrum_id or telescope or 'Spectrum'
            
            name = spectrum_label
            if phase is not None:
                name += f" - Phase: {phase:.1f}d"
            
            trace = go.Scatter(
                x=wavelengths,
                y=intensities,
                mode='lines',
                name=name,
                line=dict(
                    color=colors[i % len(colors)],
                    width=1.5
                ),
                hovertemplate=f'<b>{name}</b><br>' +
                              'Wavelength: %{x:.1f} Å<br>' +
                              'Relative Intensity: %{y:.3f}<br>' +
                              '<extra></extra>'
            )
            traces.append(trace)
        
        if not traces:
            return None
        
        x_label = 'Rest-frame Wavelength (Å)' if (rest_frame and redshift is not None) else 'Wavelength (Å)'
        y_label = 'Normalized Intensity (offset)'
        
        # Compute y-range from 4500-7000 Å window; skip when stack offsets are active
        yaxis_cfg: dict = dict(title=y_label, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
        if not stack:
            yrange = DataVisualization._yrange_from_window(all_wls_for_range, all_ints_for_range)
            if yrange:
                yaxis_cfg['range'] = yrange
        
        layout = go.Layout(
            # Left-aligned so it never collides with spectral-line labels at the top centre
            title=dict(text="All Available Spectra", x=0.01, xanchor='left',
                       font=dict(size=13, color='#9aa0a6')),
            xaxis=dict(
                title=x_label,
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)'
            ),
            yaxis=yaxis_cfg,
            template="plotly_white",
            showlegend=True,
            legend=dict(
                x=1.02,
                y=1,
                xanchor='left',
                yanchor='top'
            ),
            hovermode='x unified',
            margin=dict(l=60, r=30, t=50, b=60)
        )
        layout = DataVisualization._apply_unified_plot_style(layout, legend_right=True)

        fig = go.Figure(data=traces, layout=layout)

        # Convert to HTML div
        plot_div = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        return plot_div

# For backward compatibility
Data_Process = DataVisualization