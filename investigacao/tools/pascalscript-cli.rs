//! Read-only command-line adapter for the pinned pascalscript parser.

use std::{env, fs, io::{self, Write}, process::ExitCode};

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let path = env::args_os().nth(1).ok_or("usage: pascalscript CompiledCode.bin")?;
    let bytes = fs::read(path)?;
    let container = pascalscript::Container::parse(&bytes)?;
    let mut output = io::BufWriter::new(io::stdout().lock());
    writeln!(output, "{}", container.display_summary())?;
    for index in 0..container.proc_count() {
        if let Some(disassembly) = container.disassemble(index)? {
            writeln!(output, "\n===== proc #{index} =====")?;
            write!(output, "{}", container.display(&disassembly))?;
        }
    }
    output.flush()?;
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}
