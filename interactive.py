import os
import numpy as np
import plotly.graph_objs as go

# PATH
DATA_TEST_PATH = 'A:\_Lab\Lab_web\Lab_Data'
DATA_TEST_PATH = os.path.normpath(DATA_TEST_PATH)

# Function to create interactive spectrum plot using Plotly
def create_interactive_spectrum_plot(spectrum_file):
    data = np.loadtxt(spectrum_file)
    wavelength, intensity = data[:, 0], data[:, 1]

    # Plotly trace
    trace = go.Scatter(x=wavelength, y=intensity, mode='lines', name='Spectra')
    
    # Layout
    layout = go.Layout(
        title="Spectra",
        xaxis=dict(title="Wavelength (Å)"),
        yaxis=dict(title="Intensity"),
        template="plotly_dark"
    )
    
    # Create figure and plot
    fig = go.Figure(data=[trace], layout=layout)
    return fig.to_html(full_html=False)

# Save HTML content to a file
def save_html_plot(html_content, output_filename):
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(html_content)

# RUN
if __name__ == "__main__":
    spectrum_file = os.path.join(DATA_TEST_PATH, 'SN 2024ggi/Spectrum/SN 2024ggi_spectrum.dat')
    output_filename = os.path.join(DATA_TEST_PATH, 'SN 2024ggi/spectrum_interactive_24ggi.html')
    
    html_content = create_interactive_spectrum_plot(spectrum_file)
    save_html_plot(html_content, output_filename)
    print("Interactive plot saved to:", output_filename)
