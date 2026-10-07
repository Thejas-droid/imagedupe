"""Include dependency license notices in redistributable offline packages."""
from importlib import metadata
from pathlib import Path
import sys


def license_data():
    result=[]
    for distribution in metadata.distributions():
        name=distribution.metadata.get('Name','dependency')
        for entry in distribution.files or []:
            if entry.name.lower().startswith(('license','copying','copyright','notice')):
                path=Path(distribution.locate_file(entry))
                if path.is_file():
                    # Preserve nested license paths to avoid same-name collisions.
                    relative=Path(*entry.parts[1:]) if len(entry.parts)>1 else Path(entry.name)
                    destination=Path('licenses')/name/relative.parent
                    result.append((str(path),str(destination)))
    for filename in ('LICENSE.txt','LICENSE'):
        path=Path(sys.base_prefix)/filename
        if path.is_file():result.append((str(path),'licenses/Python'))
    tcl=Path(sys.base_prefix)/'tcl'
    if tcl.exists():
        for path in tcl.rglob('license*'):
            if path.is_file():result.append((str(path),str(Path('licenses/TclTk')/path.relative_to(tcl).parent)))
    return result
