import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from screen_context.windows_app import main
    main()
