pub fn num_cpus(default: usize) -> usize {
    std::thread::available_parallelism()
        .map(|p| p.get())
        .unwrap_or(default)
}
