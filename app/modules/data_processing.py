import os
import numpy as np
import plotly.graph_objects as go
import plotly.offline as pyo
from pathlib import Path
from datetime import datetime, timedelta, timezone
import math

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
        """Get color for different filters"""
        filter_colors = {
            # Swift UVOT 濾鏡
            'uvw2': f'rgba(106,90,205,{alpha})',
            'uvm2': f'rgba(132,112,255,{alpha})',
            'uvw1': f'rgba(123,104,238,{alpha})',
            
            # 光學濾鏡
            'u': f'rgba(75,0,130,{alpha})',        # U 濾鏡：靛藍色
            'U': f'rgba(75,0,130,{alpha})',        # U 濾鏡：靛藍色
            'B': f'rgba(0,0,255,{alpha})',         # B 濾鏡：藍色
            'b': f'rgba(0,0,255,{alpha})',         # b 濾鏡：藍色
            'g': f'rgba(44,164,112,{alpha})',      # g 濾鏡：偏綠
            'V': f'rgba(34,139,34,{alpha})',       # V 濾鏡：正綠
            'v': f'rgba(34,139,34,{alpha})',       # v 濾鏡：正綠
            'r': f'rgba(255,100,100,{alpha})',     # r 濾鏡：偏紅
            'R': f'rgba(255,0,0,{alpha})',         # R 濾鏡：紅色
            'o': f'rgba(255,165,0,{alpha})',       # o 濾鏡：橙色
            'i': f'rgba(255,105,180,{alpha})',     # i 濾鏡：粉紅
            'I': f'rgba(255,105,180,{alpha})',     # I 濾鏡：粉紅
            'z': f'rgba(139,0,0,{alpha})',         # z 濾鏡：深紅
            'Z': f'rgba(139,0,0,{alpha})',         # Z 濾鏡：深紅
            'y': f'rgba(210,105,30,{alpha})',      # y 濾鏡：棕橘色
            'Y': f'rgba(210,105,30,{alpha})',      # Y 濾鏡：棕橘色
            'w': f'rgba(46,139,87,{alpha})',       # w 濾鏡：綠意較重
            'W': f'rgba(46,139,87,{alpha})',       # W 濾鏡：綠意較重
            'c': f'rgba(138,43,226,{alpha})',      # c 濾鏡：藍紫
            'C': f'rgba(138,43,226,{alpha})',      # C 濾鏡：藍紫
            
            # 紅外線濾鏡
            'J': f'rgba(139,69,19,{alpha})',       # J 濾鏡：棕色
            'H': f'rgba(160,82,45,{alpha})',       # H 濾鏡：土紅
            'K': f'rgba(205,133,63,{alpha})',      # K 濾鏡：黃土色
            'Ks': f'rgba(205,133,63,{alpha})',     # Ks 濾鏡：黃土色
            
            # 其他濾鏡
            'L': f'rgba(0,255,255,{alpha})',       # L 濾鏡：淺色
        }
        return filter_colors.get(filter_name, f'rgba(128,128,128,{alpha})')  # 預設灰色
    
    @staticmethod
    def create_photometry_plot_from_db(photometry_data, redshift=None, ra=None, dec=None):
        """Create interactive photometry plot from database data"""
        if not photometry_data:
            return None
        
        # Group data by filter and telescope
        grouped_data = {}
        
        all_mjds = []
        all_mags = []
        
        for point in photometry_data:
            if point.get('mjd'):
                all_mjds.append(point.get('mjd'))
            if point.get('magnitude'):
                all_mags.append(point.get('magnitude'))
                
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
            
            grouped_data[key]['mjd'].append(point.get('mjd'))
            grouped_data[key]['magnitude'].append(point.get('magnitude'))
            grouped_data[key]['magnitude_error'].append(point.get('magnitude_error', 0))
        
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
                    k_correction = 2.5 * math.log10(1 + redshift)
                    
                    # Calculate extinction if RA/Dec available
                    if ra is not None and dec is not None:
                        # Use V band as reference for the axis
                        ref_filter = 'V'
                        
                        extinction_shift = ext_M_calculator.get_extinction(ra, dec, ref_filter)
                        if not isinstance(extinction_shift, (int, float)):
                            extinction_shift = 0
            except Exception as e:
                print(f"Error calculating absolute magnitude parameters: {e}")
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
            filter_specific_shift = distance_modulus + k_correction
            if ra is not None and dec is not None and ext_M_calculator:
                try:
                    ext = ext_M_calculator.get_extinction(ra, dec, filter_name)
                    if isinstance(ext, (int, float)):
                        filter_specific_shift += ext
                except Exception:
                    pass
            
            # Get symbol for telescope
            symbol = telescope_symbols.get(telescope, 'circle')
            
            # Separate points with and without errors
            with_errors = []
            without_errors = []
            
            for i, error in enumerate(data['magnitude_error']):
                if error and error > 0:
                    with_errors.append(i)
                else:
                    without_errors.append(i)
            
            # Add trace for points with error bars
            if with_errors:
                # Calculate absolute magnitudes for hover
                abs_mags = []
                for i in with_errors:
                    mag = data['magnitude'][i]
                    if mag is not None:
                        abs_mags.append(mag - filter_specific_shift)
                    else:
                        abs_mags.append(None)
                        
                trace_with_errors = go.Scatter(
                    x=[data['mjd'][i] for i in with_errors],
                    y=[data['magnitude'][i] for i in with_errors],
                    customdata=abs_mags,
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
                                  'App. Mag: %{y:.3f}<br>' +
                                  'Abs. Mag: %{customdata:.3f}<br>' +
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
            
        # Determine ranges
        min_mjd = min(all_mjds) if all_mjds else 59000
        max_mjd = max(all_mjds) if all_mjds else 59100
        pad_mjd = (max_mjd - min_mjd) * 0.05
        if pad_mjd == 0: pad_mjd = 1
        plot_min_mjd = min_mjd - pad_mjd
        plot_max_mjd = max_mjd + pad_mjd
        
        # Helper to convert MJD to Date string
        def mjd_to_date_str(mjd):
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=mjd - 40587)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
            
        plot_min_date = mjd_to_date_str(plot_min_mjd)
        plot_max_date = mjd_to_date_str(plot_max_mjd)
        
        # Create layout
        layout = go.Layout(
            title="Photometry Light Curve",
            xaxis=dict(
                title="Modified Julian Date (MJD)",
                tickformat=".2f",
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)',
                range=[plot_min_mjd, plot_max_mjd]
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
                title="Apparent Magnitude",
                tickformat=".2f",
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)'
            ),
            template="plotly_white",
            showlegend=True,
            legend=dict(
                x=1.15,
                y=1,
                xanchor='left',
                yanchor='top'
            ),
            hovermode='closest',
            margin=dict(l=60, r=150, t=80, b=60)
        )
        
        # Handle Y-axis range and Absolute Magnitude
        if all_mags:
            min_mag = min(all_mags)
            max_mag = max(all_mags)
            mag_pad = (max_mag - min_mag) * 0.1
            if mag_pad == 0: mag_pad = 0.5
            plot_min_mag = min_mag - mag_pad
            plot_max_mag = max_mag + mag_pad
            
            # Reversed Y-axis: [max, min]
            layout.yaxis.range = [plot_max_mag, plot_min_mag]
            
            if total_shift > 0:
                layout.yaxis2 = dict(
                    title="Absolute Magnitude",
                    overlaying='y',
                    side='right',
                    range=[plot_max_mag - total_shift, plot_min_mag - total_shift],
                    showgrid=False,
                    tickformat=".2f"
                )
                
                # Add dummy trace to force yaxis2 to appear
                traces.append(go.Scatter(
                    x=[plot_min_mjd],
                    y=[plot_max_mag - total_shift],
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
        
        fig = go.Figure(data=traces, layout=layout)
        
        # Convert to HTML div
        plot_div = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        return plot_div
    
    @staticmethod
    def create_spectrum_plot_from_db(spectrum_data, spectrum_id):
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
        
        # Get spectrum metadata
        telescope = spectrum_points[0].get('telescope', 'Unknown')
        phase = spectrum_points[0].get('phase')
        
        # Create trace
        trace = go.Scatter(
            x=wavelengths,
            y=intensities,
            mode='lines',
            name=f'Spectrum ({telescope})',
            line=dict(
                color='rgb(31, 119, 180)',
                width=1.5
            ),
            hovertemplate='<b>Spectrum</b><br>' +
                          'Wavelength: %{x:.1f} Å<br>' +
                          'Intensity: %{y:.3e}<br>' +
                          '<extra></extra>'
        )
        
        # Create layout
        title = f"Spectrum"
        if phase is not None:
            title += f" (Phase: {phase:.1f} days)"
        if telescope != 'Unknown':
            title += f" - {telescope}"
        
        layout = go.Layout(
            title=title,
            xaxis=dict(
                title="Wavelength (Å)",
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)'
            ),
            yaxis=dict(
                title="Relative Intensity",
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)'
            ),
            template="plotly_white",
            showlegend=False,
            hovermode='x unified',
            margin=dict(l=60, r=60, t=50, b=60)
        )
        
        fig = go.Figure(data=[trace], layout=layout)
        
        # Convert to HTML div
        plot_div = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        return plot_div
    
    @staticmethod
    def create_spectrum_list_plot_from_db(spectrum_data):
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
        colors = ['rgb(31, 119, 180)', 'rgb(255, 127, 14)', 'rgb(44, 160, 44)', 
                  'rgb(214, 39, 40)', 'rgb(148, 103, 189)', 'rgb(140, 86, 75)']
        
        for i, (spectrum_id, points) in enumerate(spectrum_groups.items()):
            # Sort by wavelength
            points.sort(key=lambda x: x.get('wavelength', 0))
            
            wavelengths = [point.get('wavelength') for point in points]
            intensities = [point.get('intensity') for point in points]
            
            # Normalize intensities for comparison
            if intensities:
                max_intensity = max(intensities)
                if max_intensity > 0:
                    intensities = [i / max_intensity + i * 0.1 for i in intensities]  # Offset for visibility
            
            telescope = points[0].get('telescope', 'Unknown')
            phase = points[0].get('phase')
            
            name = f"{spectrum_id}"
            if telescope != 'Unknown':
                name += f" ({telescope})"
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
        
        layout = go.Layout(
            title="All Available Spectra",
            xaxis=dict(
                title="Wavelength (Å)",
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)'
            ),
            yaxis=dict(
                title="Normalized Intensity (offset)",
                showgrid=True,
                gridcolor='rgba(128,128,128,0.2)'
            ),
            template="plotly_white",
            showlegend=True,
            legend=dict(
                x=1.02,
                y=1,
                xanchor='left',
                yanchor='top'
            ),
            hovermode='x unified',
            margin=dict(l=60, r=150, t=50, b=60)
        )
        
        fig = go.Figure(data=traces, layout=layout)
        
        # Convert to HTML div
        plot_div = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        return plot_div

# For backward compatibility
Data_Process = DataVisualization